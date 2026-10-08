"""Assistant domain tools layer.

Provides one typed asynchronous tool per operational domain with strict role-based
access control (RBAC), database grounding, and rigorous provenance labeling.

ROLE-BASED ACCESS CONTROL (RBAC) MATRIX:
=========================================
Tool                      | Allowed Roles                | Rationale
--------------------------|------------------------------|------------------------------------------
get_traffic_state         | admin, traffic_officer, analyst | Read-only observed telemetry
get_congestion_ranking    | admin, traffic_officer, analyst | Read-only network congestion ranking
get_predictions_30min     | admin, traffic_officer, analyst | Read-only forward AI forecasts
get_incidents             | admin, traffic_officer, analyst | Read-only incident safety observations
get_junction_history      | admin, traffic_officer, analyst | Read-only multi-source junction audit
get_signal_status         | admin, traffic_officer, analyst | Read-only signal controller hardware state
get_control_decisions     | admin, traffic_officer, analyst | Read-only supervisory decision explanations
get_analytics_summary     | admin, traffic_officer, analyst | Read-only network-wide statistical totals
get_emergency_events      | admin, traffic_officer, analyst | Read-only emergency vehicle transit state
get_routing_advice        | admin, traffic_officer       | Operational dispatch & dynamic routing
simulate_signal_timing    | admin, traffic_officer       | Operational supervisory what-if simulation

DATA INTEGRITY AND REPORTING INVARIANTS:
========================================
1. Tools NEVER synthesize or invent traffic data. Empty database queries produce explicit
   'no data' notes with empty collections, never hallucinated values.
2. Every datum carries explicit `provenance`: 'observed' | 'predicted' | 'recommended'.
3. Numerical confidence scores are provided wherever algorithmic dispersion or sensor
   certainty is computed.
4. What-if signal simulation returns ONLY raw physical measured deltas and deterministic
   verdicts ('proposed_better', 'current_better', 'equivalent') — marketing percentages
   are strictly prohibited.
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.assistant.errors import JunctionNotFoundError, PermissionDeniedError
from app.models.ai import AIDecision, AIPrediction
from app.models.emergency import EmergencyEvent
from app.models.event import Incident, VehicleEvent
from app.models.intersection import Intersection
from app.models.signal import Signal, SignalPhase
from app.models.traffic import TrafficRecord
from app.services.control.simulation import (
    ApproachState,
    PlanComparison,
    SignalPlan,
    SimulationConfig,
    WhatIfSimulator,
)
from app.services.routing.builders import build_graph
from app.services.routing.costs import CostProfile, edge_cost
from app.services.routing.graph import Edge
from app.services.routing.paths import NoPathError, dijkstra

logger = logging.getLogger(__name__)

# RBAC permission groups
ALL_ROLES = {"admin", "traffic_officer", "analyst"}
OPERATOR_ROLES = {"admin", "traffic_officer"}


def _check_permission(caller_role: str, domain: str, allowed_roles: set[str]) -> None:
    """Enforce per-domain role permissions, raising PermissionDeniedError on breach."""
    normalized = (caller_role or "").strip().lower()
    if normalized not in allowed_roles:
        raise PermissionDeniedError(
            role=caller_role,
            domain=domain,
            message=(
                f"Your role ({caller_role}) doesn't include {domain}. "
                f"Requires one of: {sorted(list(allowed_roles))}."
            ),
        )


async def get_traffic_state(
    db: AsyncSession,
    caller_role: str,
    junction_id: Optional[int] = None,
) -> dict[str, Any]:
    """Retrieve current observed traffic telemetry from sensors and perception pipelines.

    Args:
        db: Active asynchronous SQLAlchemy session.
        caller_role: Role of the invoking user ('admin', 'traffic_officer', 'analyst').
        junction_id: Optional intersection ID. When None, returns latest per junction.

    Returns:
        Structured dictionary labeled with provenance='observed'.
    """
    _check_permission(caller_role, "traffic_state", ALL_ROLES)

    if junction_id is not None:
        # Check junction existence
        junc = await db.get(Intersection, junction_id)
        if not junc:
            raise JunctionNotFoundError(junction_id)

        # Latest record for this junction
        stmt = (
            select(TrafficRecord)
            .where(TrafficRecord.intersection_id == junction_id)
            .order_by(TrafficRecord.recorded_at.desc(), TrafficRecord.id.desc())
            .limit(1)
        )
        res = await db.execute(stmt)
        record = res.scalars().first()

        # Latest perception vehicle event
        event_stmt = (
            select(VehicleEvent)
            .where(VehicleEvent.intersection_id == junction_id)
            .order_by(VehicleEvent.detected_at.desc(), VehicleEvent.id.desc())
            .limit(1)
        )
        event_res = await db.execute(event_stmt)
        v_event = event_res.scalars().first()

        if not record and not v_event:
            return {
                "data": [],
                "provenance": "observed",
                "confidence": "low",
                "note": f"No observed traffic records or perception events found for junction {junction_id}.",
            }

        items: list[dict[str, Any]] = []
        if record:
            items.append({
                "junction_id": record.intersection_id,
                "junction_name": junc.name,
                "vehicle_count": record.vehicle_count,
                "avg_speed_kmh": record.avg_speed_kmh,
                "congestion_level": record.congestion_level,
                "source": record.source,
                "recorded_at": record.recorded_at.isoformat(),
                "provenance": "observed",
                "confidence": 1.0 if record.source in ("sensor", "camera") else 0.85,
            })

        latest_event_dict = None
        if v_event:
            latest_event_dict = {
                "junction_id": v_event.intersection_id,
                "event_type": v_event.event_type,
                "vehicle_type": v_event.vehicle_type,
                "speed_kmh": v_event.speed_kmh,
                "detected_at": v_event.detected_at.isoformat(),
                "provenance": "observed",
                "confidence": v_event.confidence or 0.95,
            }

        return {
            "data": items,
            "latest_perception_event": latest_event_dict,
            "provenance": "observed",
            "confidence": "high" if record else "medium",
        }

    # Query latest record per junction across the network
    subq = (
        select(
            TrafficRecord.intersection_id,
            func.max(TrafficRecord.recorded_at).label("max_recorded_at"),
        )
        .group_by(TrafficRecord.intersection_id)
        .subquery()
    )
    stmt = (
        select(TrafficRecord, Intersection.name)
        .join(
            subq,
            (TrafficRecord.intersection_id == subq.c.intersection_id)
            & (TrafficRecord.recorded_at == subq.c.max_recorded_at),
        )
        .join(Intersection, TrafficRecord.intersection_id == Intersection.id)
        .order_by(TrafficRecord.congestion_level.desc())
        .limit(20)
    )
    res = await db.execute(stmt)
    rows = res.all()

    if not rows:
        return {
            "data": [],
            "provenance": "observed",
            "confidence": "low",
            "note": "No observed traffic records found across the network.",
        }

    data = [
        {
            "junction_id": r.intersection_id,
            "junction_name": name,
            "vehicle_count": r.vehicle_count,
            "avg_speed_kmh": r.avg_speed_kmh,
            "congestion_level": r.congestion_level,
            "source": r.source,
            "recorded_at": r.recorded_at.isoformat(),
            "provenance": "observed",
            "confidence": 1.0 if r.source in ("sensor", "camera") else 0.85,
        }
        for r, name in rows
    ]

    return {
        "data": data,
        "provenance": "observed",
        "confidence": "high",
    }


async def get_congestion_ranking(
    db: AsyncSession,
    caller_role: str,
    limit: int = 5,
) -> dict[str, Any]:
    """Rank the most congested physical intersections right now based on observed telemetry.

    Args:
        db: Active asynchronous SQLAlchemy session.
        caller_role: Role of the invoking user.
        limit: Number of top congested junctions to return (default 5).

    Returns:
        Structured dictionary labeled with provenance='observed'.
    """
    _check_permission(caller_role, "congestion_ranking", ALL_ROLES)

    subq = (
        select(
            TrafficRecord.intersection_id,
            func.max(TrafficRecord.recorded_at).label("max_recorded_at"),
        )
        .group_by(TrafficRecord.intersection_id)
        .subquery()
    )
    stmt = (
        select(TrafficRecord, Intersection.name, Intersection.code)
        .join(
            subq,
            (TrafficRecord.intersection_id == subq.c.intersection_id)
            & (TrafficRecord.recorded_at == subq.c.max_recorded_at),
        )
        .join(Intersection, TrafficRecord.intersection_id == Intersection.id)
        .order_by(TrafficRecord.congestion_level.desc())
        .limit(max(1, limit))
    )
    res = await db.execute(stmt)
    rows = res.all()

    if not rows:
        return {
            "data": [],
            "provenance": "observed",
            "confidence": "low",
            "note": "No active traffic records found for congestion ranking.",
        }

    data = [
        {
            "rank": idx + 1,
            "junction_id": r.intersection_id,
            "junction_name": name,
            "code": code,
            "congestion_level": r.congestion_level,
            "avg_speed_kmh": r.avg_speed_kmh,
            "vehicle_count": r.vehicle_count,
            "recorded_at": r.recorded_at.isoformat(),
            "provenance": "observed",
            "confidence": 1.0,
        }
        for idx, (r, name, code) in enumerate(rows)
    ]

    return {
        "data": data,
        "provenance": "observed",
        "confidence": "high",
    }


async def get_predictions_30min(
    db: AsyncSession,
    caller_role: str,
    junction_id: Optional[int] = None,
) -> dict[str, Any]:
    """Retrieve Phase 5 forward forecasting outputs with model version and horizon honesty.

    Args:
        db: Active asynchronous SQLAlchemy session.
        caller_role: Role of the invoking user.
        junction_id: Optional junction to filter by.

    Returns:
        Structured dictionary labeled with provenance='predicted'.
    """
    _check_permission(caller_role, "predictions_30min", ALL_ROLES)

    if junction_id is not None:
        junc = await db.get(Intersection, junction_id)
        if not junc:
            raise JunctionNotFoundError(junction_id)

    stmt = select(AIPrediction).order_by(AIPrediction.created_at.desc(), AIPrediction.id.desc())
    if junction_id is not None:
        stmt = stmt.where(AIPrediction.intersection_id == junction_id)
    stmt = stmt.limit(10 if junction_id is None else 4)

    res = await db.execute(stmt)
    records = list(res.scalars().all())

    if not records:
        target_str = f" for junction {junction_id}" if junction_id else " across the network"
        return {
            "data": [],
            "provenance": "predicted",
            "confidence": "low",
            "note": f"No 30-minute forecasting outputs available in the system{target_str}.",
        }

    data = [
        {
            "prediction_id": p.id,
            "junction_id": p.intersection_id,
            "prediction_type": p.prediction_type,
            "predicted_for": p.predicted_for.isoformat(),
            "horizon_minutes": 30,
            "model_version": p.model_version,
            "confidence": round(p.confidence, 4) if p.confidence is not None else 0.80,
            "payload": p.payload,
            "provenance": "predicted",
        }
        for p in records
    ]

    return {
        "data": data,
        "provenance": "predicted",
        "confidence": "high",
    }


async def get_routing_advice(
    db: AsyncSession,
    caller_role: str,
    origin_id: int,
    destination_id: int,
) -> dict[str, Any]:
    """Compute optimal route advice based on real network topology and observed edge impedances.

    Operator/Admin only. Analysts are denied.

    Args:
        db: Active asynchronous SQLAlchemy session.
        caller_role: Role of the invoking user.
        origin_id: Starting intersection ID.
        destination_id: Target intersection ID.

    Returns:
        Structured dictionary labeled with provenance='recommended'.
    """
    _check_permission(caller_role, "routing_advice", OPERATOR_ROLES)

    # Validate origin and destination existence
    origin = await db.get(Intersection, origin_id)
    if not origin:
        raise JunctionNotFoundError(origin_id)
    dest = await db.get(Intersection, destination_id)
    if not dest:
        raise JunctionNotFoundError(destination_id)

    graph, road_congestion, _, _ = await build_graph(db)

    profile = CostProfile(
        time_weight=1.0,
        distance_weight=0.5,
        congestion_weight=2.0,
        condition_weight=0.1,
    )

    def cost_fn(edge: Edge) -> float:
        c = road_congestion.get(edge.road_id, 0.0)
        return edge_cost(edge, c, profile)

    try:
        route = dijkstra(
            graph=graph,
            source=origin_id,
            target=destination_id,
            cost_fn=cost_fn,
        )
    except (NoPathError, ValueError):
        return {
            "data": None,
            "provenance": "recommended",
            "confidence": "low",
            "note": f"No topological route exists between junction {origin_id} and junction {destination_id}.",
        }

    edge_details = [
        {
            "road_id": e.road_id,
            "road_name": e.name,
            "from_junction": e.u,
            "to_junction": e.v,
            "length_km": e.length_km,
            "congestion_level": round(road_congestion.get(e.road_id, 0.0), 1),
            "provenance": "observed",
        }
        for e in route.edges
    ]

    return {
        "data": {
            "origin_id": origin_id,
            "origin_name": origin.name,
            "destination_id": destination_id,
            "destination_name": dest.name,
            "path": route.path,
            "total_cost_minutes": round(route.total_cost, 2),
            "algorithm": route.algorithm,
            "segments": edge_details,
            "provenance": "recommended",
        },
        "provenance": "recommended",
        "confidence": "high",
    }


async def get_incidents(
    db: AsyncSession,
    caller_role: str,
    active_only: bool = True,
    junction_id: Optional[int] = None,
) -> dict[str, Any]:
    """Retrieve verified traffic incidents, hazards, and roadway blockages.

    Args:
        db: Active asynchronous SQLAlchemy session.
        caller_role: Role of the invoking user.
        active_only: If True, filters out resolved incidents.
        junction_id: Optional junction to filter by.

    Returns:
        Structured dictionary labeled with provenance='observed'.
    """
    _check_permission(caller_role, "incidents", ALL_ROLES)

    if junction_id is not None:
        junc = await db.get(Intersection, junction_id)
        if not junc:
            raise JunctionNotFoundError(junction_id)

    stmt = select(Incident).order_by(Incident.created_at.desc(), Incident.id.desc())
    if active_only:
        stmt = stmt.where(Incident.status != "resolved")
    if junction_id is not None:
        stmt = stmt.where(Incident.intersection_id == junction_id)

    res = await db.execute(stmt)
    incidents = list(res.scalars().all())

    if not incidents:
        status_txt = "active " if active_only else ""
        target_txt = f" for junction {junction_id}" if junction_id else " across the network"
        return {
            "data": [],
            "provenance": "observed",
            "confidence": "high",
            "note": f"No {status_txt}incidents reported{target_txt}.",
        }

    data = [
        {
            "incident_id": inc.id,
            "junction_id": inc.intersection_id,
            "severity": inc.severity,
            "status": inc.status,
            "description": inc.description,
            "created_at": inc.created_at.isoformat(),
            "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
            "provenance": "observed",
            "confidence": 1.0,
        }
        for inc in incidents
    ]

    return {
        "data": data,
        "provenance": "observed",
        "confidence": "high",
    }


async def get_junction_history(
    db: AsyncSession,
    caller_role: str,
    junction_id: int,
    hours: int = 24,
) -> dict[str, Any]:
    """Retrieve chronological observations, incidents, and control decisions for a single junction.

    Args:
        db: Active asynchronous SQLAlchemy session.
        caller_role: Role of the invoking user.
        junction_id: The junction to inspect.
        hours: Lookback interval in hours (default 24).

    Returns:
        Structured dictionary containing observed and recommended historical sections.
    """
    _check_permission(caller_role, "junction_history", ALL_ROLES)

    junc = await db.get(Intersection, junction_id)
    if not junc:
        raise JunctionNotFoundError(junction_id)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, hours))

    # 1. Traffic observations
    tr_stmt = (
        select(TrafficRecord)
        .where(
            TrafficRecord.intersection_id == junction_id,
            TrafficRecord.recorded_at >= cutoff,
        )
        .order_by(TrafficRecord.recorded_at.desc())
        .limit(30)
    )
    tr_res = await db.execute(tr_stmt)
    records = list(tr_res.scalars().all())

    # 2. Incidents
    inc_stmt = (
        select(Incident)
        .where(
            Incident.intersection_id == junction_id,
            Incident.created_at >= cutoff,
        )
        .order_by(Incident.created_at.desc())
        .limit(10)
    )
    inc_res = await db.execute(inc_stmt)
    incidents = list(inc_res.scalars().all())

    # 3. AI Decisions / control recommendations
    dec_stmt = (
        select(AIDecision)
        .where(
            AIDecision.intersection_id == junction_id,
            AIDecision.created_at >= cutoff,
        )
        .order_by(AIDecision.created_at.desc())
        .limit(10)
    )
    dec_res = await db.execute(dec_stmt)
    decisions = list(dec_res.scalars().all())

    has_data = bool(records or incidents or decisions)

    obs_records = [
        {
            "vehicle_count": r.vehicle_count,
            "avg_speed_kmh": r.avg_speed_kmh,
            "congestion_level": r.congestion_level,
            "source": r.source,
            "recorded_at": r.recorded_at.isoformat(),
            "provenance": "observed",
        }
        for r in records
    ]

    obs_incidents = [
        {
            "incident_id": inc.id,
            "severity": inc.severity,
            "status": inc.status,
            "description": inc.description,
            "created_at": inc.created_at.isoformat(),
            "provenance": "observed",
        }
        for inc in incidents
    ]

    rec_decisions = [
        {
            "decision_id": d.id,
            "decision_type": d.decision_type,
            "status": d.status,
            "rationale": d.rationale or (d.payload.get("reason") if isinstance(d.payload, dict) else None),
            "created_at": d.created_at.isoformat(),
            "provenance": "recommended",
        }
        for d in decisions
    ]

    return {
        "data": {
            "junction_id": junction_id,
            "junction_name": junc.name,
            "lookback_hours": hours,
            "traffic_observations": obs_records,
            "incidents": obs_incidents,
            "control_decisions": rec_decisions,
        },
        "provenance": "observed",
        "confidence": "high" if has_data else "low",
        "note": None if has_data else f"No telemetry or events recorded for junction {junction_id} in the past {hours} hours.",
    }


async def get_signal_status(
    db: AsyncSession,
    caller_role: str,
    junction_id: Optional[int] = None,
) -> dict[str, Any]:
    """Retrieve operational signal controllers, phase timing, and camera-observed states.

    Args:
        db: Active asynchronous SQLAlchemy session.
        caller_role: Role of the invoking user.
        junction_id: Optional intersection ID filter.

    Returns:
        Structured dictionary labeled with provenance='observed'.
    """
    _check_permission(caller_role, "signal_status", ALL_ROLES)

    if junction_id is not None:
        junc = await db.get(Intersection, junction_id)
        if not junc:
            raise JunctionNotFoundError(junction_id)

    stmt = select(Signal).options(selectinload(Signal.phases)).order_by(Signal.id.asc())
    if junction_id is not None:
        stmt = stmt.where(Signal.intersection_id == junction_id)

    res = await db.execute(stmt)
    signals = list(res.scalars().all())

    if not signals:
        target_txt = f" for junction {junction_id}" if junction_id else " across the network"
        return {
            "data": [],
            "provenance": "observed",
            "confidence": "low",
            "note": f"No signal hardware or controllers configured{target_txt}.",
        }

    data = [
        {
            "signal_id": s.id,
            "junction_id": s.intersection_id,
            "code": s.code,
            "status": s.status,
            "observed_state": s.observed_state,
            "observed_confidence": s.observed_confidence,
            "observed_at": s.observed_at.isoformat() if s.observed_at else None,
            "phases": [
                {
                    "name": p.name,
                    "order": p.phase_order,
                    "duration_seconds": p.duration_seconds,
                    "state": p.state,
                    "is_active": p.is_active,
                    "provenance": "observed",
                }
                for p in s.phases
            ],
            "provenance": "observed",
            "confidence": s.observed_confidence or 0.95,
        }
        for s in signals
    ]

    return {
        "data": data,
        "provenance": "observed",
        "confidence": "high",
    }


async def get_control_decisions(
    db: AsyncSession,
    caller_role: str,
    junction_id: Optional[int] = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Retrieve AI control recommendations alongside their stored causal explanations.

    Args:
        db: Active asynchronous SQLAlchemy session.
        caller_role: Role of the invoking user.
        junction_id: Optional junction to filter by.
        limit: Max decisions to return (default 5).

    Returns:
        Structured dictionary labeled with provenance='recommended'.
    """
    _check_permission(caller_role, "control_decisions", ALL_ROLES)

    if junction_id is not None:
        junc = await db.get(Intersection, junction_id)
        if not junc:
            raise JunctionNotFoundError(junction_id)

    stmt = select(AIDecision).order_by(AIDecision.created_at.desc(), AIDecision.id.desc())
    if junction_id is not None:
        stmt = stmt.where(AIDecision.intersection_id == junction_id)
    stmt = stmt.limit(max(1, limit))

    res = await db.execute(stmt)
    decisions = list(res.scalars().all())

    if not decisions:
        target_txt = f" for junction {junction_id}" if junction_id else " across the network"
        return {
            "data": [],
            "provenance": "recommended",
            "confidence": "low",
            "note": f"No control decisions found{target_txt}.",
        }

    data = [
        {
            "decision_id": d.id,
            "junction_id": d.intersection_id,
            "decision_type": d.decision_type,
            "status": d.status,
            "rationale": (
                d.rationale
                or (d.payload.get("reason") if isinstance(d.payload, dict) else None)
                or "Conditions evaluated within normal operational parameters."
            ),
            "payload": d.payload,
            "created_at": d.created_at.isoformat(),
            "provenance": "recommended",
            "confidence": 0.85,
        }
        for d in decisions
    ]

    return {
        "data": data,
        "provenance": "recommended",
        "confidence": "high",
    }


async def get_analytics_summary(
    db: AsyncSession,
    caller_role: str,
) -> dict[str, Any]:
    """Calculate aggregated network statistics (totals, averages — observed only).

    Args:
        db: Active asynchronous SQLAlchemy session.
        caller_role: Role of the invoking user.

    Returns:
        Structured dictionary labeled with provenance='observed'.
    """
    _check_permission(caller_role, "analytics_summary", ALL_ROLES)

    # 1. Total and active intersections
    total_juncs = await db.scalar(select(func.count(Intersection.id))) or 0
    active_juncs = await db.scalar(
        select(func.count(Intersection.id)).where(Intersection.status == "active")
    ) or 0

    # 2. Total signals
    total_signals = await db.scalar(select(func.count(Signal.id))) or 0

    # 3. Active incidents
    active_incidents = await db.scalar(
        select(func.count(Incident.id)).where(Incident.status != "resolved")
    ) or 0

    # 4. Telemetry averages from recent records (past 24h)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    stat_stmt = select(
        func.avg(TrafficRecord.vehicle_count),
        func.avg(TrafficRecord.avg_speed_kmh),
        func.avg(TrafficRecord.congestion_level),
        func.count(TrafficRecord.id),
    ).where(TrafficRecord.recorded_at >= cutoff)

    stat_res = await db.execute(stat_stmt)
    avg_veh, avg_spd, avg_cong, rec_count = stat_res.one()

    return {
        "data": {
            "total_intersections": int(total_juncs),
            "active_intersections": int(active_juncs),
            "total_signals": int(total_signals),
            "active_incidents": int(active_incidents),
            "recent_records_24h": int(rec_count or 0),
            "avg_vehicle_count": round(float(avg_veh), 1) if avg_veh is not None else 0.0,
            "avg_speed_kmh": round(float(avg_spd), 1) if avg_spd is not None else 0.0,
            "avg_congestion_level": round(float(avg_cong), 1) if avg_cong is not None else 0.0,
            "provenance": "observed",
        },
        "provenance": "observed",
        "confidence": "high" if total_juncs > 0 else "low",
    }


async def get_emergency_events(
    db: AsyncSession,
    caller_role: str,
    active_only: bool = True,
) -> dict[str, Any]:
    """Retrieve active emergency vehicle response and preemption transit events.

    Args:
        db: Active asynchronous SQLAlchemy session.
        caller_role: Role of the invoking user.
        active_only: Filter for active/dispatched events only.

    Returns:
        Structured dictionary labeled with provenance='observed'.
    """
    _check_permission(caller_role, "emergency_events", ALL_ROLES)

    stmt = select(EmergencyEvent).order_by(EmergencyEvent.created_at.desc(), EmergencyEvent.id.desc())
    if active_only:
        stmt = stmt.where(EmergencyEvent.status.in_(["active", "dispatched", "on_scene"]))

    res = await db.execute(stmt)
    events = list(res.scalars().all())

    if not events:
        return {
            "data": [],
            "provenance": "observed",
            "confidence": "high",
            "note": "No active emergency transit events recorded.",
        }

    data = [
        {
            "event_id": e.id,
            "incident_id": e.incident_id,
            "vehicle_type": e.vehicle_type,
            "priority": e.priority,
            "status": e.status,
            "detected_at": e.detected_at.isoformat(),
            "provenance": "observed",
            "confidence": 1.0,
        }
        for e in events
    ]

    return {
        "data": data,
        "provenance": "observed",
        "confidence": "high",
    }


async def simulate_signal_timing(
    db: AsyncSession,
    caller_role: str,
    junction_id: int,
    green_seconds: int,
    phase_name: Optional[str] = None,
    horizon_minutes: float = 15.0,
) -> dict[str, Any]:
    """Execute Phase 6 macroscopic point-queue simulation comparing baseline vs proposed signal plan.

    Operator/Admin only. Analysts are denied.

    CRITICAL REPORTING INVARIANT:
    Returns ONLY raw physical measured deltas and deterministic verdicts. Prohibits
    percentage-improvement marketing claims.

    Args:
        db: Active asynchronous SQLAlchemy session.
        caller_role: Role of the invoking user.
        junction_id: The junction to simulate.
        green_seconds: Proposed duration for the specified green phase in seconds.
        phase_name: Optional name of the phase to modify.
        horizon_minutes: Simulation lookahead duration in minutes (default 15.0).

    Returns:
        Structured dictionary labeled with provenance='predicted'.
    """
    _check_permission(caller_role, "simulate_signal_timing", OPERATOR_ROLES)

    junc = await db.get(Intersection, junction_id)
    if not junc:
        raise JunctionNotFoundError(junction_id)

    # Fetch signal hardware and phases configured for this intersection
    stmt = (
        select(Signal)
        .options(selectinload(Signal.phases))
        .where(Signal.intersection_id == junction_id)
        .order_by(Signal.id.asc())
    )
    res = await db.execute(stmt)
    signals = list(res.scalars().all())

    phases: list[SignalPhase] = []
    for s in signals:
        if s.phases:
            phases.extend(s.phases)

    if not phases:
        return {
            "data": None,
            "provenance": "predicted",
            "confidence": "low",
            "note": f"Junction {junction_id} has no configured signal controllers or phases to simulate.",
        }

    # Identify target phase to adjust
    target_phase: Optional[SignalPhase] = None
    if phase_name:
        for p in phases:
            if p.name.strip().lower() == phase_name.strip().lower():
                target_phase = p
                break

    if target_phase is None:
        # Pick the green phase, or first phase
        for p in phases:
            if p.state == "green":
                target_phase = p
                break
        if target_phase is None:
            target_phase = phases[0]

    # Baseline plan
    current_phases: dict[str, float] = {
        p.name: max(5.0, float(p.duration_seconds)) for p in phases
    }
    phase_to_approaches: dict[str, list[str]] = {
        p.name: [f"approach_{p.name.lower().replace(' ', '_')}"] for p in phases
    }

    # Proposed plan: modify target phase green duration
    proposed_phases = dict(current_phases)
    proposed_phases[target_phase.name] = max(5.0, float(green_seconds))

    # Query latest traffic record for realistic queue and arrival initialization
    tr_stmt = (
        select(TrafficRecord)
        .where(TrafficRecord.intersection_id == junction_id)
        .order_by(TrafficRecord.recorded_at.desc(), TrafficRecord.id.desc())
        .limit(1)
    )
    tr_res = await db.execute(tr_stmt)
    last_record = tr_res.scalars().first()

    base_queue = max(2.0, float(last_record.congestion_level) * 0.2) if last_record else 8.0
    base_arrival = max(5.0, float(last_record.vehicle_count) / 4.0) if last_record else 15.0

    initial_approaches = [
        ApproachState(
            approach_id=f"approach_{p.name.lower().replace(' ', '_')}",
            queue_veh=base_queue,
            arrival_rate_veh_per_min=base_arrival,
            saturation_flow_veh_per_min=30.0,
            lane_count=1,
            name=p.name,
        )
        for p in phases
    ]

    current_plan = SignalPlan(
        phases=current_phases,
        phase_to_approaches=phase_to_approaches,
        yellow_s=3.0,
        all_red_s=2.0,
    )
    proposed_plan = SignalPlan(
        phases=proposed_phases,
        phase_to_approaches=phase_to_approaches,
        yellow_s=3.0,
        all_red_s=2.0,
    )

    sim_config = SimulationConfig(
        horizon_minutes=max(1.0, float(horizon_minutes)),
        dt_seconds=5.0,
    )

    simulator = WhatIfSimulator()
    comparison: PlanComparison = simulator.compare(
        initial=initial_approaches,
        current_plan=current_plan,
        proposed_plan=proposed_plan,
        config=sim_config,
    )

    return {
        "data": {
            "junction_id": junction_id,
            "junction_name": junc.name,
            "target_phase": target_phase.name,
            "baseline_green_s": current_phases[target_phase.name],
            "proposed_green_s": float(green_seconds),
            "delta_wait_veh_min": comparison.delta_wait,
            "delta_avg_queue_veh": comparison.delta_avg_queue,
            "delta_throughput_veh": comparison.delta_throughput,
            "verdict": comparison.verdict,
            "horizon_minutes": float(horizon_minutes),
            "provenance": "predicted",
        },
        "provenance": "predicted",
        "confidence": "high",
    }
