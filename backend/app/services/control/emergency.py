"""Emergency vehicle green-corridor priority preemption orchestrator (Phase 6 Part 3).

CRITICAL ARCHITECTURAL SAFETY INVARIANT:
----------------------------------------
This module produces AI RECOMMENDATIONS only.
It does NOT physically control field hardware; NO direct controller integration exists.
All decisions emitted by this orchestrator are supervisory recommendations (`is_recommendation=True`).
The system NEVER directly actuates physical conflict monitors (MMUs/CMUs), bypasses
local failsafes, or commands field signal controllers without human supervisory authorization
or compliant NTCIP field translation.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import functools
import logging
from typing import Any, Callable, Optional, Sequence, Union

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ai import AIDecision
from app.models.emergency import EmergencyEvent
from app.models.event import Incident
from app.models.signal import Signal, SignalPhase
from app.services.control.decisions import TrafficStateBuilder
from app.services.control.exceptions import InsufficientDataError, UnsafeStateError
from app.services.control.optimization import CycleConfig
from app.services.control.persistence import DecisionStore
from app.services.control.safety import SafetyValidator
from app.services.control.schemas import Decision, DecisionAction, TrafficState
from app.services.routing.builders import build_graph
from app.services.routing.dispatch import DispatchQueue
from app.services.routing.green_corridor import (
    CorridorSignalAction,
    GreenCorridorPlan,
    plan_green_corridor,
)
from app.services.routing.paths import haversine_km

logger = logging.getLogger(__name__)


@dataclass
class EmergencyDecision:
    """Advisory emergency green corridor preemption recommendation.

    Attributes:
        decision: The persisted advisory Decision recommendation (`is_recommendation=True`).
        corridor_plan: Calculated green wave route and signal preemption plan.
        affected_intersection_ids: Ordered list of junction IDs along the corridor path.
    """

    decision: Decision
    corridor_plan: GreenCorridorPlan
    affected_intersection_ids: list[int]


class _DualMethod:
    """Descriptor enabling an async method to be called cleanly on either class or instance."""

    def __init__(self, func: Callable[..., Any]) -> None:
        self.func = func
        functools.update_wrapper(self, func)

    def __get__(self, instance: Any, owner: Any) -> Callable[..., Any]:
        if instance is None:
            # Called as Class.method(...)
            async def class_wrapper(*args: Any, **kwargs: Any) -> Any:
                inst = owner()
                return await self.func(inst, *args, **kwargs)

            return class_wrapper

        # Called as instance.method(...)
        async def instance_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await self.func(instance, *args, **kwargs)

        return instance_wrapper


class EmergencyPriorityOrchestrator:
    """Supervisory emergency preemption and green corridor route orchestrator.

    CRITICAL ARCHITECTURAL SAFETY INVARIANT:
    ----------------------------------------
    Produces AI RECOMMENDATIONS only. NEVER commands field signal controller hardware.
    All decisions returned or persisted carry `is_recommendation=True`.
    """

    def __init__(self, cycle_config: Optional[CycleConfig] = None) -> None:
        """Initialize the emergency priority orchestrator.

        Args:
            cycle_config: Operational cycle timing boundaries for safety validation.
                Defaults to CycleConfig(min_green_s=5.0, max_green_s=120.0).
        """
        self.cycle_config = cycle_config or CycleConfig(min_green_s=5.0, max_green_s=120.0)

    @_DualMethod
    async def prioritize(
        self,
        session: AsyncSession,
        emergency_event_id: int,
        destination_intersection_id: int,
        graph_cache: Optional[dict[str, Any]] = None,
        cycle_config: Optional[CycleConfig] = None,
    ) -> EmergencyDecision:
        """Calculate, validate, and record an advisory emergency green corridor recommendation.

        GRAPH CACHE CONTRACT:
        ---------------------
        The `graph_cache` parameter is a caller-owned mutable dictionary.
        If populated with keys ('graph', 'road_congestion', 'node_coords', 'code_to_id'),
        the orchestrator reuses these pre-built in-memory objects directly, avoiding redundant
        database hydration queries. If empty or missing these keys, the orchestrator invokes
        `build_graph(session)` and stores the hydrated graph, road congestion, coordinate,
        and municipal code mappings back into `graph_cache` for subsequent calls.

        SAFETY VALIDATION GUARANTEE:
        ----------------------------
        Every signal action in the planned corridor is validated against real database
        Signal and SignalPhase records:
        1. Timing Bounds: `SafetyValidator.validate_timing` ensures proposed duration is within
           [min_green_s, max_green_s].
        2. Conflict Freedom: `SafetyValidator.check_conflicts` checks concurrent green movements
           against phase directional definitions.
        If ANY action fails validation, strictly raises UnsafeStateError and aborts without
        producing or persisting a corridor plan (fail-safe invariant).

        Args:
            session: Active asynchronous SQLAlchemy database session.
            emergency_event_id: Identifier of the EmergencyEvent to prioritize.
            destination_intersection_id: Target hospital/incident junction identifier.
            graph_cache: Caller-owned dict cache for hydrated road network components.
            cycle_config: Optional timing boundaries override for safety validation.

        Returns:
            EmergencyDecision containing persisted advisory Decision, GreenCorridorPlan,
            and ordered list of affected intersection IDs.

        Raises:
            ValueError: If the emergency event does not exist or its status is not 'active'.
            InsufficientDataError: If the emergency vehicle origin junction cannot be determined
                from linked incident intersection_id or geographic coordinates.
            UnsafeStateError: If any proposed corridor signal action fails safety validation.
        """
        effective_config = cycle_config or getattr(self, "cycle_config", None) or CycleConfig(
            min_green_s=5.0, max_green_s=120.0
        )

        # 1. Load the EmergencyEvent; verify it is active
        stmt = (
            select(EmergencyEvent)
            .options(selectinload(EmergencyEvent.incident))
            .where(EmergencyEvent.id == emergency_event_id)
        )
        res = await session.execute(stmt)
        event = res.scalar_one_or_none()

        if event is None:
            raise ValueError(f"EmergencyEvent with id {emergency_event_id} not found.")

        if event.status != "active":
            raise ValueError(
                f"Emergency event {emergency_event_id} has status '{event.status}', expected 'active'."
            )

        # 2. Build / hydrate graph via Phase 3 builder, respecting caller-owned graph_cache contract
        if graph_cache is None:
            graph_cache = {}

        if (
            isinstance(graph_cache, dict)
            and "graph" in graph_cache
            and "road_congestion" in graph_cache
            and "node_coords" in graph_cache
        ):
            graph = graph_cache["graph"]
            road_congestion = graph_cache["road_congestion"]
            node_coords = graph_cache["node_coords"]
            code_to_id = graph_cache.get("code_to_id", {})
        else:
            graph, road_congestion, node_coords, code_to_id = await build_graph(session)
            if isinstance(graph_cache, dict):
                graph_cache["graph"] = graph
                graph_cache["road_congestion"] = road_congestion
                graph_cache["node_coords"] = node_coords
                graph_cache["code_to_id"] = code_to_id

        # 3. Determine the emergency vehicle origin junction (never guess)
        origin_intersection_id: Optional[int] = None

        if event.incident and event.incident.intersection_id is not None:
            origin_intersection_id = event.incident.intersection_id
        elif event.incident_id is not None:
            inc_stmt = select(Incident).where(Incident.id == event.incident_id)
            inc_res = await session.execute(inc_stmt)
            linked_inc = inc_res.scalar_one_or_none()
            if linked_inc and linked_inc.intersection_id is not None:
                origin_intersection_id = linked_inc.intersection_id
                if event.incident is None:
                    event.incident = linked_inc

        # Fallback to coordinates on linked incident or event if intersection_id is missing
        if origin_intersection_id is None:
            lat = getattr(event.incident, "lat", None) if getattr(event, "incident", None) else None
            lon = getattr(event.incident, "lon", None) if getattr(event, "incident", None) else None
            if lat is None:
                lat = getattr(event, "lat", None)
            if lon is None:
                lon = getattr(event, "lon", None)

            if lat is not None and lon is not None:
                if not node_coords:
                    raise InsufficientDataError(
                        f"Emergency event {emergency_event_id} has geographic coordinates ({lat}, {lon}) "
                        "but network graph has no intersection node coordinates to map to a junction."
                    )
                # Determine nearest intersection using great-circle haversine distance
                nearest_id: Optional[int] = None
                min_dist = float("inf")
                for junc_id, (j_lat, j_lon) in node_coords.items():
                    dist = haversine_km(float(lat), float(lon), float(j_lat), float(j_lon))
                    if dist < min_dist:
                        min_dist = dist
                        nearest_id = junc_id
                origin_intersection_id = nearest_id

        if origin_intersection_id is None:
            raise InsufficientDataError(
                f"Emergency event {emergency_event_id} has no location data "
                "(missing linked incident intersection_id and lat/lon coordinates); "
                "cannot determine origin junction without guessing."
            )

        # 4. Plan green corridor
        corridor_plan: GreenCorridorPlan = await plan_green_corridor(
            session=session,
            graph=graph,
            road_congestion=road_congestion,
            node_coords=node_coords,
            from_intersection_id=origin_intersection_id,
            to_intersection_id=destination_intersection_id,
        )

        # 5. Rigorous safety validation of every signal action in the plan against real DB rows
        for action in corridor_plan.signal_actions:
            if action.signal_id is None or action.action == "monitor":
                continue

            sig_stmt = (
                select(Signal)
                .options(selectinload(Signal.phases))
                .where(Signal.id == action.signal_id)
            )
            sig_res = await session.execute(sig_stmt)
            sig_row = sig_res.scalar_one_or_none()

            if sig_row is None:
                raise UnsafeStateError(
                    f"Signal controller {action.signal_id} referenced in corridor plan does not exist in database."
                )

            phases = list(sig_row.phases)
            if not phases:
                raise UnsafeStateError(
                    f"Signal controller {action.signal_id} at intersection {action.intersection_id} "
                    "has no configured signal phases."
                )

            # Identify target green phase
            target_phase = next((p for p in phases if p.state.lower() == "green"), None)
            if target_phase is None:
                active_phases = [p for p in phases if p.is_active]
                if not active_phases:
                    raise UnsafeStateError(
                        f"Signal controller {action.signal_id} has no active phases for green extension."
                    )
                target_phase = active_phases[0]

            if not target_phase.is_active:
                raise UnsafeStateError(
                    f"Cannot extend green on inactive phase {target_phase.id} ('{target_phase.name}') "
                    f"for signal {action.signal_id}."
                )

            # 5a. Timing bounds validation
            SafetyValidator.validate_timing(
                signal_id=action.signal_id,
                phase_id=target_phase.id,
                proposed_green_s=action.duration_seconds,
                config=effective_config,
            )

            # 5b. Conflict detection across all phases at the junction
            inter_phase_stmt = (
                select(SignalPhase)
                .where(SignalPhase.intersection_id == action.intersection_id)
            )
            inter_phase_res = await session.execute(inter_phase_stmt)
            all_intersection_phases = list(inter_phase_res.scalars().all())
            if not all_intersection_phases:
                all_intersection_phases = phases

            currently_green = [p.id for p in all_intersection_phases if p.state.lower() == "green"]
            green_ids = list(set(currently_green + [target_phase.id]))
            SafetyValidator.check_conflicts(
                phases=all_intersection_phases,
                green_phase_ids=green_ids,
            )

        # 6. Safety validation passed — construct and persist advisory Decision
        affected_signal_ids = [
            action.signal_id
            for action in corridor_plan.signal_actions
            if action.signal_id is not None
        ]

        try:
            current_state = await TrafficStateBuilder.build(session, origin_intersection_id)
            if not current_state.active_emergency:
                from dataclasses import replace

                current_state = replace(current_state, active_emergency=True)
        except Exception:
            current_state = TrafficState(
                intersection_id=origin_intersection_id,
                vehicle_count=0,
                density=0.0,
                queue_length=0.0,
                occupancy=0.0,
                active_emergency=True,
                source="emergency_orchestrator",
            )

        decision = Decision(
            intersection_id=origin_intersection_id,
            action=DecisionAction.ACTIVATE_GREEN_CORRIDOR,
            current=current_state,
            predicted=None,
            reason=(
                f"Green corridor activated from intersection {corridor_plan.from_intersection_id} "
                f"to {corridor_plan.to_intersection_id} along path {corridor_plan.path} "
                f"with ETA {corridor_plan.estimated_minutes:.2f} mins affecting {len(corridor_plan.path)} intersections."
            ),
            expected_impact=(
                f"Preempt downstream traffic signals along corridor ({len(affected_signal_ids)} signals) "
                "to minimize emergency transit latency and eliminate cross-traffic collision hazards."
            ),
            confidence=None,
            affected_signal_ids=affected_signal_ids,
            affected_route={
                "corridor_id": corridor_plan.corridor_id,
                "path": corridor_plan.path,
                "estimated_minutes": corridor_plan.estimated_minutes,
                "emergency_event_id": emergency_event_id,
            },
            is_recommendation=True,
        )

        await DecisionStore.save(session, decision)

        # 7. Transition emergency event active -> dispatched
        event.status = "dispatched"
        await session.flush()

        return EmergencyDecision(
            decision=decision,
            corridor_plan=corridor_plan,
            affected_intersection_ids=list(corridor_plan.path),
        )

    @_DualMethod
    async def restore(
        self,
        session: AsyncSession,
        emergency_event_id: int,
    ) -> Decision:
        """Restore normal signal operations after an emergency priority period concludes.

        CRITICAL ARCHITECTURAL SAFETY INVARIANT:
        ----------------------------------------
        Never touches real hardware. This produces an advisory NO_ACTION recommendation
        indicating that supervisory preemption has ended and signals may return to
        their standard cyclic coordination plan.

        Args:
            session: Active asynchronous SQLAlchemy database session.
            emergency_event_id: Identifier of the EmergencyEvent to conclude.

        Returns:
            The persisted NO_ACTION Decision recommendation.

        Raises:
            ValueError: If the emergency event record does not exist.
        """
        stmt = (
            select(EmergencyEvent)
            .options(selectinload(EmergencyEvent.incident))
            .where(EmergencyEvent.id == emergency_event_id)
        )
        res = await session.execute(stmt)
        event = res.scalar_one_or_none()

        if event is None:
            raise ValueError(f"EmergencyEvent with id {emergency_event_id} not found.")

        # Transition status dispatched -> resolved (only if dispatched or on_scene)
        if event.status in ("dispatched", "on_scene"):
            event.status = "resolved"
            event.cleared_at = datetime.now(timezone.utc)

        # Verify corridor decisions linked to this event
        dec_stmt = (
            select(AIDecision)
            .where(AIDecision.decision_type == DecisionAction.ACTIVATE_GREEN_CORRIDOR.value)
            .order_by(AIDecision.created_at.desc())
        )
        dec_res = await session.execute(dec_stmt)
        all_corridor_decisions = dec_res.scalars().all()

        corridor_decisions = [
            d
            for d in all_corridor_decisions
            if isinstance(d.payload, dict)
            and (
                d.payload.get("affected_route", {}).get("emergency_event_id") == emergency_event_id
                or d.payload.get("emergency_event_id") == emergency_event_id
            )
        ]

        intersection_id = 0
        restored_signal_ids: list[int] = []

        if corridor_decisions:
            intersection_id = corridor_decisions[0].intersection_id
            for cd in corridor_decisions:
                if isinstance(cd.payload, dict):
                    sig_ids = cd.payload.get("affected_signal_ids", [])
                    if isinstance(sig_ids, list):
                        restored_signal_ids.extend([s for s in sig_ids if isinstance(s, int)])
            restored_signal_ids = sorted(list(set(restored_signal_ids)))
        elif event.incident and event.incident.intersection_id:
            intersection_id = event.incident.intersection_id

        # Persist NO_ACTION decision returning signals to baseline
        restore_decision = Decision(
            intersection_id=intersection_id,
            action=DecisionAction.NO_ACTION,
            current=TrafficState(
                intersection_id=intersection_id,
                vehicle_count=0,
                density=0.0,
                queue_length=0.0,
                occupancy=0.0,
                active_emergency=False,
                source="emergency_restore",
            ),
            predicted=None,
            reason="emergency priority period ended — signals return to normal plan (recommendation)",
            expected_impact="Resume standard cyclic signal timings and phase progression across corridor intersections.",
            confidence=None,
            affected_signal_ids=restored_signal_ids,
            affected_route={"emergency_event_id": emergency_event_id, "restored": True},
            is_recommendation=True,
        )

        await DecisionStore.save(session, restore_decision)
        await session.flush()
        return restore_decision

    @_DualMethod
    async def resolve_conflicts(
        self,
        session: AsyncSession,
        emergency_event_ids: Sequence[int],
    ) -> dict[int, str]:
        """Resolve competing preemption requests claiming identical intersection right-of-way.

        TRAFFIC ENGINEERING PRIORITY CONVENTION:
        ----------------------------------------
        Matches the multi-attribute dispatch triage convention from `app.services.routing.dispatch`:
        1. Event Severity: Critical outranks high, medium, low.
        2. Emergency Priority: Evaluated using `DispatchQueue` ordering where higher priority
           integers indicate higher operational urgency.
        3. FIFO Fairness: Older timestamps take precedence among identical priority rankings.

        The winning emergency retains 'primary' status. Competing emergencies claiming the same
        junction are marked 'deferred' and receive a persisted PRIORITIZE_EMERGENCY decision
        citing the deferral reason and affected signals.

        Args:
            session: Active asynchronous SQLAlchemy database session.
            emergency_event_ids: Sequence of emergency event primary key IDs to triage.

        Returns:
            Dictionary mapping emergency event ID -> 'primary' | 'deferred'.
        """
        if not emergency_event_ids:
            return {}

        ev_stmt = (
            select(EmergencyEvent)
            .options(selectinload(EmergencyEvent.incident))
            .where(EmergencyEvent.id.in_(list(emergency_event_ids)))
        )
        ev_res = await session.execute(ev_stmt)
        events = list(ev_res.scalars().all())

        if not events:
            return {}

        event_map = {ev.id: ev for ev in events}

        # 1. Map each emergency to its claimed junction(s)
        event_intersections: dict[int, set[int]] = defaultdict(set)
        for ev in events:
            if ev.incident and ev.incident.intersection_id is not None:
                event_intersections[ev.id].add(ev.incident.intersection_id)
            elif ev.incident_id is not None:
                inc_stmt = select(Incident).where(Incident.id == ev.incident_id)
                inc_res = await session.execute(inc_stmt)
                inc = inc_res.scalar_one_or_none()
                if inc and inc.intersection_id is not None:
                    event_intersections[ev.id].add(inc.intersection_id)

            if hasattr(ev, "intersection_id") and getattr(ev, "intersection_id", None) is not None:
                event_intersections[ev.id].add(getattr(ev, "intersection_id"))

        # Also inspect active green corridor decisions for route path intersections
        cd_stmt = (
            select(AIDecision)
            .where(AIDecision.decision_type == DecisionAction.ACTIVATE_GREEN_CORRIDOR.value)
        )
        cd_res = await session.execute(cd_stmt)
        for cd in cd_res.scalars().all():
            if isinstance(cd.payload, dict):
                ev_id = (
                    cd.payload.get("affected_route", {}).get("emergency_event_id")
                    or cd.payload.get("emergency_event_id")
                )
                if ev_id in event_intersections:
                    path = cd.payload.get("affected_route", {}).get("path", [])
                    if isinstance(path, list):
                        event_intersections[ev_id].update(path)

        # 2. Group events by intersection to detect right-of-way collisions
        events_by_intersection: dict[int, list[EmergencyEvent]] = defaultdict(list)
        for ev_id, junc_set in event_intersections.items():
            ev = event_map[ev_id]
            for junc_id in junc_set:
                events_by_intersection[junc_id].append(ev)

        result: dict[int, str] = {ev.id: "primary" for ev in events}

        # Helper ranking emergencies using DispatchQueue multi-attribute triage
        def rank_events(ev_list: list[EmergencyEvent]) -> list[EmergencyEvent]:
            q = DispatchQueue()
            for e in ev_list:
                q.push_emergency(e)
            ranked: list[EmergencyEvent] = []
            while q:
                item = q.pop()
                ranked.append(event_map[item.ref_id])
            return ranked

        # 3. Resolve conflicts at overlapping intersections
        for junc_id, conflicting in events_by_intersection.items():
            if len(conflicting) <= 1:
                continue

            ranked = rank_events(conflicting)
            winner = ranked[0]
            losers = ranked[1:]

            for loser in losers:
                result[loser.id] = "deferred"

                # Query real signals installed at the contested intersection
                sig_stmt = (
                    select(Signal.id)
                    .where(Signal.intersection_id == junc_id)
                    .order_by(Signal.id.asc())
                )
                sig_res = await session.execute(sig_stmt)
                sig_ids = list(sig_res.scalars().all())

                deferred_decision = Decision(
                    intersection_id=junc_id,
                    action=DecisionAction.PRIORITIZE_EMERGENCY,
                    current=TrafficState(
                        intersection_id=junc_id,
                        vehicle_count=0,
                        density=0.0,
                        queue_length=0.0,
                        occupancy=0.0,
                        active_emergency=True,
                        source="emergency_conflict_resolution",
                    ),
                    predicted=None,
                    reason=f"deferred: higher-priority emergency {winner.id} active at intersection {junc_id}",
                    expected_impact=f"Yield right-of-way at intersection {junc_id} to primary emergency {winner.id}.",
                    confidence=0.85,
                    affected_signal_ids=sig_ids,
                    affected_route={
                        "emergency_event_id": loser.id,
                        "deferred_to_emergency_id": winner.id,
                        "contested_intersection_id": junc_id,
                    },
                    is_recommendation=True,
                )
                await DecisionStore.save(session, deferred_decision)

        await session.flush()
        return result
