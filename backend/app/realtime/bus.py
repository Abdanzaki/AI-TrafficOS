"""Asynchronous Redis EventBus for AI TrafficOS real-time communication.

Combines Redis Streams (durable retention and reconnect replay) with
Redis Pub/Sub (instant, low-overhead fan-out across WebSocket instances).
Includes deduplication guards, non-blocking safe publishing, and degraded-mode
tolerance if Redis is offline.
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional, Union
from uuid import UUID, uuid4

import redis.asyncio as aioredis
from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import get_logger
from app.realtime.events import EventEnvelope, EventType

logger = get_logger(__name__)


class EventBus:
    """Async Redis event bus managing real-time event streaming and fan-out.

    Architecture:
        - Stream Key: Durable append-only log trimmed to ~10,000 entries. Used
          by clients to catch up on missed deltas after reconnecting.
        - Pub/Sub Channel: Ephemeral broadcast channel used to fan out events
          to active WebSocket connections in memory.
        - Deduplication Guard: SETNX key with 1-hour TTL keyed by event_id.
          Prevents duplicate events from being injected during network retries.
        - Degraded Mode: If Redis is unreachable at startup or during execution,
          publishing becomes a logged no-op and subscription yields nothing.
          The API continues to function without crashing.
    """

    DEFAULT_STREAM_KEY = "trafficos:events"
    DEFAULT_PUBSUB_CHANNEL = "trafficos:events:pubsub"
    DEDUPE_KEY_PREFIX = "trafficos:event:"
    DEFAULT_STREAM_MAXLEN = 10000
    DEFAULT_DEDUPE_TTL = 3600  # 1 hour in seconds

    def __init__(
        self,
        redis_url: Optional[str] = None,
        stream_key: str = DEFAULT_STREAM_KEY,
        pubsub_channel: str = DEFAULT_PUBSUB_CHANNEL,
        stream_maxlen: int = DEFAULT_STREAM_MAXLEN,
        dedupe_ttl: int = DEFAULT_DEDUPE_TTL,
    ) -> None:
        """Initialize EventBus configuration. Connection is established lazily or via connect()."""
        self.redis_url: str = redis_url or settings.REDIS_URL
        self.stream_key: str = stream_key
        self.pubsub_channel: str = pubsub_channel
        self.stream_maxlen: int = stream_maxlen
        self.dedupe_ttl: int = dedupe_ttl
        self._redis: Optional[Redis] = None
        self._connected: bool = False
        self._degraded: bool = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def is_connected(self) -> bool:
        """Return True if the bus is actively connected to Redis."""
        return self._connected and self._redis is not None

    @property
    def is_degraded(self) -> bool:
        """Return True if the bus is running in degraded mode (Redis unreachable)."""
        return self._degraded

    async def connect(self) -> None:
        """Connect to Redis.

        Pings the server to ensure reachability. If Redis is down or unreachable,
        logs a warning and enters DEGRADED mode so the application can still boot.
        """
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if self._connected and self._redis is not None and (self._loop is None or self._loop is current_loop):
            return

        if self._loop is not None and current_loop is not None and self._loop is not current_loop:
            self._connected = False
            self._redis = None

        self._loop = current_loop

        try:
            self._redis = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=2.0,
                socket_timeout=5.0,
            )
            await self._redis.ping()
            self._connected = True
            self._degraded = False
            logger.info("EventBus connected successfully to Redis at %s", self.redis_url)
        except Exception as exc:
            logger.warning(
                "EventBus failed to connect to Redis at %s: %s. Running in DEGRADED mode.",
                self.redis_url,
                exc,
            )
            self._connected = False
            self._degraded = True
            if self._redis is not None:
                try:
                    await self._redis.aclose()
                except Exception:
                    pass
                self._redis = None

    async def close(self) -> None:
        """Gracefully close the Redis client connection and clean up resources."""
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception as exc:
                logger.warning("Error closing EventBus Redis connection: %s", exc)
            finally:
                self._redis = None
                self._connected = False
                self._loop = None

    async def _ensure_connected(self) -> None:
        """Ensure Redis connection has been attempted."""
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if self._loop is not None and current_loop is not None and self._loop is not current_loop:
            self._connected = False
            self._redis = None
            self._degraded = False

        if not self._connected and not self._degraded:
            await self.connect()

    def _build_envelope(
        self,
        event_type: Union[EventType, str, EventEnvelope],
        payload: Optional[dict[str, Any]] = None,
        source: Optional[str] = None,
        event_id: Optional[Union[UUID, str]] = None,
    ) -> EventEnvelope:
        """Construct an EventEnvelope instance if not already provided."""
        if isinstance(event_type, EventEnvelope):
            return event_type

        resolved_id: UUID
        if event_id is None:
            resolved_id = uuid4()
        elif isinstance(event_id, UUID):
            resolved_id = event_id
        else:
            resolved_id = UUID(str(event_id))

        return EventEnvelope(
            event_id=resolved_id,
            type=event_type,  # type: ignore[arg-type]
            timestamp=datetime.now(timezone.utc),
            payload=payload if payload is not None else {},
            source=source or "unknown",
        )

    async def publish(
        self,
        event_type: Union[EventType, str, EventEnvelope],
        payload: Optional[dict[str, Any]] = None,
        source: Optional[str] = None,
        event_id: Optional[Union[UUID, str]] = None,
    ) -> EventEnvelope:
        """Publish an event to the Redis Stream and Pub/Sub channel.

        1. Builds a canonical EventEnvelope (UUIDv4 dedupe key, UTC server timestamp).
        2. Applies deduplication guard using SETNX on 'trafficos:event:{event_id}' with 1h TTL.
           If the key already exists, publish is a no-op returning the existing envelope.
        3. Appends the serialized envelope to Redis STREAM 'trafficos:events' with ~10000 MAXLEN trim.
        4. Publishes the serialized envelope to Redis pub/sub channel 'trafficos:events:pubsub'.

        If running in DEGRADED mode, publishing is a logged no-op and returns the envelope.
        """
        await self._ensure_connected()
        envelope = self._build_envelope(event_type, payload=payload, source=source, event_id=event_id)

        if self._degraded or self._redis is None:
            logger.warning(
                "EventBus is running in DEGRADED mode; publish dropped as no-op for %s (id: %s)",
                envelope.type,
                envelope.event_id,
            )
            return envelope

        dedupe_key = f"{self.DEDUPE_KEY_PREFIX}{envelope.event_id}"
        serialized = envelope.model_dump_json()

        # Deduplication guard: SET key val NX EX 3600
        is_new = await self._redis.set(
            dedupe_key,
            serialized,
            nx=True,
            ex=self.dedupe_ttl,
        )

        if not is_new:
            logger.info("Event %s already published; dedupe guard hit, returning existing envelope", envelope.event_id)
            existing_raw = await self._redis.get(dedupe_key)
            if existing_raw:
                try:
                    return EventEnvelope.model_validate_json(existing_raw)
                except Exception:
                    pass
            return envelope

        # Write to durable stream with approximate trimming
        await self._redis.xadd(
            self.stream_key,
            {"data": serialized, "event_id": str(envelope.event_id)},
            maxlen=self.stream_maxlen,
            approximate=True,
        )

        # Publish to live fan-out pub/sub channel
        await self._redis.publish(self.pubsub_channel, serialized)

        return envelope

    async def safe_publish(
        self,
        event_type: Union[EventType, str, EventEnvelope],
        payload: Optional[dict[str, Any]] = None,
        source: Optional[str] = None,
        event_id: Optional[Union[UUID, str]] = None,
    ) -> Optional[EventEnvelope]:
        """Safe wrapper around publish that never raises exceptions.

        Logs failures and returns None. Fast and non-blocking for endpoint call sites.
        """
        try:
            if self._degraded:
                logger.warning(
                    "EventBus in DEGRADED mode; safe_publish dropping event %s",
                    getattr(event_type, "type", event_type),
                )
                return None
            return await self.publish(
                event_type,
                payload=payload,
                source=source,
                event_id=event_id,
            )
        except Exception as exc:
            logger.error(
                "safe_publish failed for event (type=%s, source=%s): %s",
                getattr(event_type, "type", event_type),
                source,
                exc,
                exc_info=True,
            )
            return None

    def _parse_stream_entry(self, fields: dict[str, Any]) -> Optional[EventEnvelope]:
        """Parse stream entry fields into an EventEnvelope, logging if malformed."""
        try:
            if "data" in fields:
                return EventEnvelope.model_validate_json(fields["data"])
            return EventEnvelope.model_validate(fields)
        except Exception as exc:
            logger.warning("Skipping malformed stream entry during replay: %s", exc)
            return None

    async def read_since(
        self,
        last_event_id: Optional[Union[UUID, str]],
    ) -> tuple[list[EventEnvelope], bool]:
        """Read events from Redis Stream since the specified last_event_id.

        Args:
            last_event_id: The UUID or string representation of the last received event ID.
                If None, returns all events currently in the stream.

        Returns:
            tuple[list[EventEnvelope], bool]: A list of subsequent EventEnvelope objects
            in order, and a boolean 'stale' flag. If last_event_id was provided but
            not found in the stream (trimmed due to MAXLEN or unknown), returns ([], True).
        """
        await self._ensure_connected()

        if self._degraded or self._redis is None:
            logger.warning("EventBus is in DEGRADED mode; read_since returning ([], True)")
            return ([], True)

        try:
            entries = await self._redis.xrange(self.stream_key, min="-", max="+")
        except Exception as exc:
            logger.error("Failed to read stream %s: %s", self.stream_key, exc)
            return ([], True)

        if not entries:
            if last_event_id is None:
                return ([], False)
            return ([], True)

        if last_event_id is None:
            events: list[EventEnvelope] = []
            for _, fields in entries:
                env = self._parse_stream_entry(fields)
                if env is not None:
                    events.append(env)
            return (events, False)

        target_id = str(last_event_id)
        match_idx = -1

        for idx, (_, fields) in enumerate(entries):
            entry_event_id = fields.get("event_id")
            if not entry_event_id and "data" in fields:
                try:
                    parsed = json.loads(fields["data"])
                    entry_event_id = parsed.get("event_id")
                except Exception:
                    pass
            if entry_event_id == target_id:
                match_idx = idx
                break

        if match_idx == -1:
            # last_event_id was not found in the stream (trimmed or unknown)
            return ([], True)

        events: list[EventEnvelope] = []
        for _, fields in entries[match_idx + 1 :]:
            env = self._parse_stream_entry(fields)
            if env is not None:
                events.append(env)

        return (events, False)

    async def subscribe(self) -> AsyncGenerator[EventEnvelope, None]:
        """Subscribe to the live fan-out Redis Pub/Sub channel.

        Yields:
            Validated EventEnvelope objects. Skips and logs malformed payloads.

        Notes:
            If in DEGRADED mode, yields nothing and exits immediately.
        """
        await self._ensure_connected()

        if self._degraded or self._redis is None:
            logger.warning("EventBus is in DEGRADED mode; subscribe yielding nothing")
            return

        pubsub = self._redis.pubsub()
        try:
            await pubsub.subscribe(self.pubsub_channel)
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if not data:
                    continue
                try:
                    envelope = EventEnvelope.model_validate_json(data)
                    yield envelope
                except Exception as exc:
                    logger.warning("Skipping malformed pub/sub message: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Error in pub/sub subscription on %s: %s", self.pubsub_channel, exc)
        finally:
            try:
                await pubsub.unsubscribe(self.pubsub_channel)
            except Exception:
                pass
            try:
                await pubsub.aclose()
            except Exception:
                pass
