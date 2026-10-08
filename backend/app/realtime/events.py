"""Event schemas and constants for AI TrafficOS real-time communication.

Defines the canonical EventEnvelope model and event types used across
the Redis Streams durable event log and Redis Pub/Sub fan-out channels.
"""

from datetime import datetime, timezone
from typing import Any, Literal, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

# Canonical event type constants
TRAFFIC_UPDATE = "traffic.update"
CONGESTION_CHANGE = "congestion.change"
SIGNAL_CHANGE = "signal.change"
INCIDENT_CREATED = "incident.created"
INCIDENT_UPDATED = "incident.updated"
EMERGENCY_CREATED = "emergency.created"
EMERGENCY_UPDATED = "emergency.updated"
PREDICTION_PUBLISHED = "prediction.published"
CONTROL_DECISION = "control.decision"
NOTIFICATION_CREATED = "notification.created"
SYSTEM_STATUS = "system.status"

EventType = Literal[
    "traffic.update",
    "congestion.change",
    "signal.change",
    "incident.created",
    "incident.updated",
    "emergency.created",
    "emergency.updated",
    "prediction.published",
    "control.decision",
    "notification.created",
    "system.status",
]

ALL_EVENT_TYPES: tuple[str, ...] = (
    TRAFFIC_UPDATE,
    CONGESTION_CHANGE,
    SIGNAL_CHANGE,
    INCIDENT_CREATED,
    INCIDENT_UPDATED,
    EMERGENCY_CREATED,
    EMERGENCY_UPDATED,
    PREDICTION_PUBLISHED,
    CONTROL_DECISION,
    NOTIFICATION_CREATED,
    SYSTEM_STATUS,
)


class EventEnvelope(BaseModel):
    """Canonical real-time event envelope.

    Payload Guidance:
        - Payloads MUST contain only small deltas (e.g. entity IDs, changed fields,
          numeric sensor metrics, or state transitions).
        - Payloads MUST NEVER contain sensitive data, including secrets, API tokens,
          passwords, private keys, or password hashes.
        - Payloads must be JSON-serializable dictionaries.

    Attributes:
        event_id: Deduplication key uniquely identifying the event. Generated
            server-side as a UUIDv4.
        type: Standardized event type string classifying the payload.
        timestamp: Server time in UTC when the event occurred/was produced.
        payload: Lightweight delta dictionary describing the state change.
        source: Producing subsystem or service identifier (e.g. 'signals-api',
            'control-engine', 'incident-service').
    """

    event_id: UUID = Field(
        default_factory=uuid4,
        description="Server-generated unique identifier and deduplication key",
    )
    type: EventType = Field(
        ...,
        description="Standardized event type classification",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC server timestamp of event generation",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Lightweight delta payload containing IDs and changed fields",
    )
    source: str = Field(
        ...,
        description="Subsystem or service producing the event (e.g. 'signals-api')",
    )

    model_config = ConfigDict(
        populate_by_name=True,
    )
