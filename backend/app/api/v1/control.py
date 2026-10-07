"""Intelligent Traffic Control REST API router (Phase 6 Part 5).

Provides supervisory, advisory traffic control endpoints conforming to NTCIP signal conventions:
- Recommendations formulated from real-time telemetry and predictive forecasts
- Queue-proportional Webster-inspired signal timing optimization
- Macroscopic point-queue what-if plan simulation and comparison
- Emergency green-corridor priority preemption and normal plan restoration
- Read-only green-corridor route and timing recommendations
- Decision lifecycle inspection, application, and revocation
- Real-time junction control status overview
"""

from datetime import datetime, timezone
import logging
import math
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_active_user, get_current_user, require_roles
from app.api.v1.auth import get_client_ip
from app.core.audit import log_audit
from app.core.database import get_db
from app.models.ai import AIDecision, AIPrediction
from app.models.auth import User
from app.models.emergency import EmergencyEvent
from app.models.event import Incident
from app.models.intersection import Intersection
from app.models.road import Road
from app.models.signal import Signal, SignalPhase
from app.models.traffic import TrafficRecord
from app.schemas.control import (
    ApproachSimulationResultResponse,
    ApproachStateInput,
    CorridorSignalActionResponse,
    CycleConfigInput,
    DecisionItemResponse,
    DecisionResponse,
    EmergencyPrioritizeRequest,
    EmergencyPrioritizeResponse,
    EmergencyRestoreRequest,
    EmergencyRestoreResponse,
    GreenCorridorPlanResponse,
    GreenCorridorRecommendRequest,
    GreenCorridorRecommendResponse,
    JunctionControlStatusResponse,
    LatestDecisionSummary,
    LatestPredictionSummary,
    OptimizeSignalsRequest,
    OptimizeSignalsResponse,
    PaginatedDecisionsResponse,
    PhaseDemandInput,
    PlanComparisonResponse,
    PredictedStateResponse,
    RecommendationRequest,
    SignalPlanInput,
    SimulateRequest,
    SimulationResultResponse,
    TrafficStateResponse,
)
from app.services.control.decisions import DecisionEngine, TrafficStateBuilder
from app.services.control.emergency import EmergencyDecision, EmergencyPriorityOrchestrator
from app.services.control.exceptions import (
    InsufficientDataError,
    StaleTelemetryError,
    UnsafeStateError,
)
from app.services.control.optimization import (
    CycleConfig,
    OptimizationResult,
    PhaseDemand,
    SignalOptimizer,
)
from app.services.control.persistence import DecisionStore
from app.services.control.safety import SafetyValidator
from app.services.control.schemas import (
    Decision,
    DecisionAction,
    PredictedState,
    TrafficState,
)
from app.services.control.simulation import (
    ApproachState,
    PlanComparison,
    SignalPlan,
    SimulationConfig,
    WhatIfSimulator,
)
from app.services.forecasting import (
    ForecastingInsufficientDataError,
    ForecastingModelNotFoundError,
    predict_and_store,
)
from app.services.routing.builders import build_graph
from app.services.routing.green_corridor import plan_green_corridor
from app.services.routing.paths import NoPathError

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/control",
    tags=["control"],
    dependencies=[Depends(get_current_user)],
)

# Module-level cached graph dictionary to reuse network topology across requests
_GRAPH_CACHE: dict[str, Any] = {}


async def _get_or_build_graph(
    db: AsyncSession, refresh: bool = False
) -> tuple[Any, dict[int, float], dict[int, tuple[float, float]], dict[str, int]]:
    """Retrieve in-memory graph from module-level cache or rebuild from database."""
    if refresh or "graph" not in _GRAPH_CACHE:
        graph, road_congestion, node_coords, code_to_id = await build_graph(db)
        _GRAPH_CACHE["graph"] = graph
        _GRAPH_CACHE["road_congestion"] = road_congestion
        _GRAPH_CACHE["node_coords"] = node_coords
        _GRAPH_CACHE["code_to_id"] = code_to_id
    return (
        _GRAPH_CACHE["graph"],
        _GRAPH_CACHE["road_congestion"],
        _GRAPH_CACHE["node_coords"],
        _GRAPH_CACHE["code_to_id"],
    )


# ==============================================================================
# 1. POST /recommendations
# ==============================================================================


@router.post(
    "/recommendations",
    response_model=DecisionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate supervisory control recommendation for intersection",
)
async def create_recommendation(
    payload: RecommendationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> DecisionResponse:
    """Evaluate live telemetry and ML forecasts to propose an advisory signal control decision.

    Guarantees:
    - Never actuates field hardware directly (`is_recommendation=True`).
    - Stale telemetry (> 300s) raises 422 Unprocessable Entity.
    - If predictive forecasts are unavailable or insufficient, degrades gracefully with predicted=None.
    - Persists advisory decision in `ai_decisions` table with status 'proposed'.
    - Records audit trail event 'control.recommendation'.
    """
    # 1. Verify intersection exists
    inter_stmt = select(Intersection).where(Intersection.id == payload.intersection_id)
    inter_res = await db.execute(inter_stmt)
    if inter_res.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Intersection {payload.intersection_id} not found.",
        )

    # 2. Build live TrafficState from telemetry
    try:
        state = await TrafficStateBuilder.build(db, payload.intersection_id)
    except StaleTelemetryError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.message,
        )

    # 3. Fetch latest prediction for intersection via forecasting service
    predicted: Optional[PredictedState] = None
    try:
        forecast_results = await predict_and_store(db, [payload.intersection_id])
        if forecast_results and forecast_results[0].get("status") == "predicted":
            res0 = forecast_results[0]
            flow_info = res0.get("flow", {})
            cong_info = res0.get("congestion", {})
            predicted = PredictedState(
                congestion=float(cong_info.get("value", 0.0)),
                volume=float(flow_info.get("value", 0.0)),
                queue_growth=float(cong_info.get("queue", 0.0)),
                horizon_minutes=30,
                model_version=res0.get("model_version"),
                confidence=(
                    float(cong_info.get("confidence", 0.0))
                    if cong_info.get("confidence") is not None
                    else None
                ),
            )
    except (ForecastingModelNotFoundError, ForecastingInsufficientDataError, Exception) as exc:
        logger.info(
            "Forecasting unavailable or insufficient for intersection %d: %s; degrading gracefully.",
            payload.intersection_id,
            exc,
        )
        predicted = None

    # 4. Evaluate deterministic control rules and propose recommendation
    engine = DecisionEngine()
    decision = await engine.propose_with_session(db, state, predicted)

    # 5. Persist decision in database
    await DecisionStore.save(db, decision, decided_by_user_id=current_user.id)

    # 6. Record audit log
    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="control.recommendation",
        actor_user_id=current_user.id,
        entity_type="ai_decision",
        entity_id=decision.id,
        details={
            "intersection_id": decision.intersection_id,
            "action": decision.action.value,
            "confidence": decision.confidence,
            "reason": decision.reason,
        },
        ip_address=client_ip,
    )
    await db.commit()

    return DecisionResponse(
        id=decision.id,
        intersection_id=decision.intersection_id,
        action=decision.action.value,
        current=TrafficStateResponse(**decision.current.to_dict()),
        predicted=(
            PredictedStateResponse(**decision.predicted.to_dict())
            if decision.predicted is not None
            else None
        ),
        reason=decision.reason,
        expected_impact=decision.expected_impact,
        confidence=decision.confidence,
        affected_signal_ids=decision.affected_signal_ids,
        affected_route=decision.affected_route,
        model_version=decision.model_version,
        created_at=decision.created_at,
        is_recommendation=True,
    )


# ==============================================================================
# 2. POST /optimize-signals
# ==============================================================================


@router.post(
    "/optimize-signals",
    response_model=OptimizeSignalsResponse,
    status_code=status.HTTP_200_OK,
    summary="Calculate queue-proportional signal timing optimization (officer/admin)",
)
async def optimize_signals(
    payload: OptimizeSignalsRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> OptimizeSignalsResponse:
    """Calculate queue-proportional Webster-inspired green splits and perform safety validation.

    Guarantees:
    - Validates that all phases exist and belong to the specified intersection (404 otherwise).
    - Runs SignalOptimizer.optimize to distribute cycle green budget proportionally.
    - Authoritative SafetyValidator.validate_plan verifies timing bounds, cyclic order, and conflicts.
    - If unsafe state is detected, raises 422 Unprocessable Entity with detail.
    - Emits audit log event 'control.signal_optimization'.
    """
    # 1. Verify intersection exists
    inter_stmt = select(Intersection.id).where(Intersection.id == payload.intersection_id)
    inter_res = await db.execute(inter_stmt)
    if inter_res.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Intersection {payload.intersection_id} not found.",
        )

    # 2. Fetch and validate configured phases belonging to this intersection
    phase_stmt = (
        select(SignalPhase)
        .outerjoin(Signal, SignalPhase.signal_id == Signal.id)
        .where(
            (SignalPhase.intersection_id == payload.intersection_id)
            | (Signal.intersection_id == payload.intersection_id)
        )
    )
    phase_res = await db.execute(phase_stmt)
    phases = list(phase_res.scalars().all())
    phase_map = {p.id: p for p in phases}

    for d in payload.phase_demands:
        if d.phase_id not in phase_map:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Phase {d.phase_id} does not belong to intersection {payload.intersection_id}.",
            )

    # 3. Instantiate cycle configuration
    if payload.cycle_config is not None:
        try:
            cycle_config = CycleConfig(
                min_green_s=payload.cycle_config.min_green_s,
                max_green_s=payload.cycle_config.max_green_s,
                yellow_s=payload.cycle_config.yellow_s,
                all_red_s=payload.cycle_config.all_red_s,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            )
    else:
        cycle_config = CycleConfig()

    # 4. Map demand inputs to domain PhaseDemand structures
    domain_demands = [
        PhaseDemand(
            phase_id=d.phase_id,
            phase_name=phase_map[d.phase_id].name,
            queue_length=d.queue_length,
            density=d.density,
            flow_veh_per_min=d.flow_veh_per_min,
            predicted_congestion=d.predicted_congestion,
            predicted_queue_growth=d.predicted_queue_growth,
            lane_count=d.lane_count,
            is_emergency_route=d.is_emergency_route,
        )
        for d in payload.phase_demands
    ]

    # 5. Execute Webster-inspired green split allocation
    opt_result = SignalOptimizer.optimize(
        demands=domain_demands,
        cycle_config=cycle_config,
    )

    # 6. Rigorous safety validation
    try:
        SafetyValidator.validate_plan(
            intersection_id=payload.intersection_id,
            proposed_greens=opt_result.recommended_green_s,
            phases=phases,
            config=cycle_config,
        )
    except UnsafeStateError as exc:
        msg = str(exc)
        detail_msg = msg if "unsafe" in msg.lower() else f"unsafe state: {msg}"
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail_msg,
        )

    # 7. Audit logging
    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="control.signal_optimization",
        actor_user_id=current_user.id,
        entity_type="intersection",
        entity_id=payload.intersection_id,
        details={
            "recommended_green_s": opt_result.recommended_green_s,
            "total_cycle_s": opt_result.total_cycle_s,
            "method": opt_result.method,
        },
        ip_address=client_ip,
    )
    await db.commit()

    return OptimizeSignalsResponse(
        intersection_id=payload.intersection_id,
        recommended_green_s=opt_result.recommended_green_s,
        total_cycle_s=opt_result.total_cycle_s,
        method=opt_result.method,
        inputs_echo=opt_result.inputs_echo,
        computed_at=opt_result.computed_at,
        note=opt_result.note,
        validated=True,
    )


# ==============================================================================
# 3. POST /simulate
# ==============================================================================


@router.post(
    "/simulate",
    response_model=PlanComparisonResponse,
    status_code=status.HTTP_200_OK,
    summary="Simulate and compare baseline vs proposed signal timing plans",
)
async def simulate_plans(
    payload: SimulateRequest,
    current_user: User = Depends(get_current_active_user),
) -> PlanComparisonResponse:
    """Execute pure macroscopic point-queue traffic simulation comparing two signal timing plans.

    Guarantees:
    - Pure in-memory computation; executes zero database writes.
    - Prohibits percentage-improvement claims; reports raw physical deltas and deterministic verdict.
    - Raises 422 Unprocessable Entity if input geometries or timings violate operational bounds.
    """
    try:
        domain_approaches = [
            ApproachState(
                approach_id=a.approach_id,
                queue_veh=a.queue_veh,
                arrival_rate_veh_per_min=a.arrival_rate_veh_per_min,
                saturation_flow_veh_per_min=a.saturation_flow_veh_per_min,
                lane_count=a.lane_count,
                name=a.name,
            )
            for a in payload.approaches
        ]
        current_signal_plan = SignalPlan(
            phases=payload.current_plan.phases,
            phase_to_approaches=payload.current_plan.phase_to_approaches,
            yellow_s=payload.current_plan.yellow_s,
            all_red_s=payload.current_plan.all_red_s,
        )
        proposed_signal_plan = SignalPlan(
            phases=payload.proposed_plan.phases,
            phase_to_approaches=payload.proposed_plan.phase_to_approaches,
            yellow_s=payload.proposed_plan.yellow_s,
            all_red_s=payload.proposed_plan.all_red_s,
        )
        sim_config = SimulationConfig(
            horizon_minutes=payload.horizon_minutes if payload.horizon_minutes is not None else 15.0,
            dt_seconds=payload.dt_seconds if payload.dt_seconds is not None else 5.0,
        )
        simulator = WhatIfSimulator()
        comparison: PlanComparison = simulator.compare(
            initial=domain_approaches,
            current_plan=current_signal_plan,
            proposed_plan=proposed_signal_plan,
            config=sim_config,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    return PlanComparisonResponse.model_validate(comparison.to_dict())


# ==============================================================================
# 4. POST /emergency/prioritize and POST /emergency/restore
# ==============================================================================


@router.post(
    "/emergency/prioritize",
    response_model=EmergencyPrioritizeResponse,
    status_code=status.HTTP_200_OK,
    summary="Activate advisory green corridor preemption for emergency transit (officer/admin)",
)
async def emergency_prioritize(
    payload: EmergencyPrioritizeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> EmergencyPrioritizeResponse:
    """Plan, validate, and record an advisory emergency vehicle green wave preemption corridor.

    Guarantees:
    - Never commands physical signal controllers (`is_recommendation=True`).
    - Validates each signal action against real database controllers and safety constraints.
    - Raises 404 if emergency event does not exist; 422 if origin data missing, path missing, or unsafe.
    - Transitions emergency event status from active to dispatched.
    - Logs audit record 'control.emergency_prioritize'.
    """
    orchestrator = EmergencyPriorityOrchestrator()
    try:
        emergency_dec: EmergencyDecision = await orchestrator.prioritize(
            session=db,
            emergency_event_id=payload.emergency_event_id,
            destination_intersection_id=payload.destination_intersection_id,
            graph_cache=_GRAPH_CACHE,
        )
    except ValueError as exc:
        msg = str(exc).lower()
        if "not found" in msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except NoPathError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except InsufficientDataError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    except UnsafeStateError as exc:
        msg = str(exc)
        detail_msg = msg if "unsafe" in msg.lower() else f"unsafe state: {msg}"
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail_msg)

    # Record audit log
    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="control.emergency_prioritize",
        actor_user_id=current_user.id,
        entity_type="emergency_event",
        entity_id=payload.emergency_event_id,
        details={
            "destination_intersection_id": payload.destination_intersection_id,
            "corridor_id": emergency_dec.corridor_plan.corridor_id,
            "decision_id": emergency_dec.decision.id,
            "path": emergency_dec.corridor_plan.path,
        },
        ip_address=client_ip,
    )
    await db.commit()

    cp = emergency_dec.corridor_plan
    return EmergencyPrioritizeResponse(
        decision_id=emergency_dec.decision.id,
        corridor_plan=GreenCorridorPlanResponse(
            corridor_id=cp.corridor_id,
            path=cp.path,
            signal_actions=[
                CorridorSignalActionResponse(
                    intersection_id=sa.intersection_id,
                    signal_id=sa.signal_id,
                    action=sa.action,
                    duration_seconds=sa.duration_seconds,
                    reason=sa.reason,
                )
                for sa in cp.signal_actions
            ],
            estimated_minutes=round(cp.estimated_minutes, 3),
            from_intersection_id=cp.from_intersection_id,
            to_intersection_id=cp.to_intersection_id,
        ),
        affected_intersection_ids=emergency_dec.affected_intersection_ids,
        is_recommendation=True,
    )


@router.post(
    "/emergency/restore",
    response_model=EmergencyRestoreResponse,
    status_code=status.HTTP_200_OK,
    summary="Conclude emergency preemption and restore standard signal plan (officer/admin)",
)
async def emergency_restore(
    payload: EmergencyRestoreRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> EmergencyRestoreResponse:
    """Restore normal cyclic signal operation following completion of emergency transit.

    Guarantees:
    - Never commands field hardware directly; emits an advisory NO_ACTION recommendation.
    - Transitions dispatched emergency event to resolved status with cleared_at timestamp.
    - Emits audit log record 'control.emergency_restore'.
    """
    orchestrator = EmergencyPriorityOrchestrator()
    try:
        restore_dec = await orchestrator.restore(
            session=db,
            emergency_event_id=payload.emergency_event_id,
        )
    except ValueError as exc:
        msg = str(exc).lower()
        if "not found" in msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="control.emergency_restore",
        actor_user_id=current_user.id,
        entity_type="emergency_event",
        entity_id=payload.emergency_event_id,
        details={
            "decision_id": restore_dec.id,
            "action": restore_dec.action.value,
            "affected_signal_ids": restore_dec.affected_signal_ids,
        },
        ip_address=client_ip,
    )
    await db.commit()

    return EmergencyRestoreResponse(
        decision_id=restore_dec.id,
        emergency_event_id=payload.emergency_event_id,
        action=restore_dec.action.value,
        reason=restore_dec.reason,
        affected_signal_ids=restore_dec.affected_signal_ids,
        is_recommendation=True,
    )


# ==============================================================================
# 5. POST /green-corridor/recommend
# ==============================================================================


@router.post(
    "/green-corridor/recommend",
    response_model=GreenCorridorRecommendResponse,
    status_code=status.HTTP_200_OK,
    summary="Compute advisory green wave preemption corridor recommendation (officer/admin)",
)
async def recommend_green_corridor(
    payload: GreenCorridorRecommendRequest,
    refresh: bool = Query(False, description="Rebuild cached network graph"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> GreenCorridorRecommendResponse:
    """Calculate and safety-validate a candidate emergency green corridor WITHOUT persisting changes.

    CRITICAL SAFETY & CONTRACT NOTE:
    --------------------------------
    This is a READ-ONLY supervisory planning recommendation.
    It executes graph pathfinding and verifies all prospective signal actions against safety bounds,
    but does NOT persist an AIDecision record, does NOT alter emergency event statuses, and does NOT
    actuate field hardware.
    """
    graph, road_congestion, node_coords, _ = await _get_or_build_graph(db, refresh=refresh)

    try:
        plan = await plan_green_corridor(
            session=db,
            graph=graph,
            road_congestion=road_congestion,
            node_coords=node_coords,
            from_intersection_id=payload.from_intersection_id,
            to_intersection_id=payload.to_intersection_id,
            emergency_speed_kmh=payload.emergency_speed_kmh,
        )
    except (NoPathError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    # Comprehensive safety validation on planned corridor signal actions
    effective_config = CycleConfig(min_green_s=5.0, max_green_s=120.0)
    for action in plan.signal_actions:
        if action.signal_id is None or action.action == "monitor":
            continue

        sig_stmt = (
            select(Signal)
            .options(selectinload(Signal.phases))
            .where(Signal.id == action.signal_id)
        )
        sig_res = await db.execute(sig_stmt)
        sig_row = sig_res.scalar_one_or_none()

        if sig_row is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"unsafe state: Signal controller {action.signal_id} does not exist in database.",
            )

        phases = list(sig_row.phases)
        if not phases:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"unsafe state: Signal controller {action.signal_id} has no configured signal phases.",
            )

        target_phase = next((p for p in phases if p.state.lower() == "green"), None)
        if target_phase is None:
            active_phases = [p for p in phases if p.is_active]
            if not active_phases:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"unsafe state: Signal controller {action.signal_id} has no active phases.",
                )
            target_phase = active_phases[0]

        if not target_phase.is_active:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"unsafe state: Cannot extend green on inactive phase {target_phase.id} for signal {action.signal_id}.",
            )

        try:
            SafetyValidator.validate_timing(
                signal_id=action.signal_id,
                phase_id=target_phase.id,
                proposed_green_s=action.duration_seconds,
                config=effective_config,
            )
        except UnsafeStateError as exc:
            msg = str(exc)
            detail_msg = msg if "unsafe" in msg.lower() else f"unsafe state: {msg}"
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=detail_msg,
            )

        inter_phase_stmt = (
            select(SignalPhase)
            .where(SignalPhase.intersection_id == action.intersection_id)
        )
        inter_phase_res = await db.execute(inter_phase_stmt)
        all_intersection_phases = list(inter_phase_res.scalars().all())
        if not all_intersection_phases:
            all_intersection_phases = phases

        currently_green = [p.id for p in all_intersection_phases if p.state.lower() == "green"]
        green_ids = list(set(currently_green + [target_phase.id]))
        try:
            SafetyValidator.check_conflicts(
                phases=all_intersection_phases,
                green_phase_ids=green_ids,
            )
        except UnsafeStateError as exc:
            msg = str(exc)
            detail_msg = msg if "unsafe" in msg.lower() else f"unsafe state: {msg}"
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=detail_msg,
            )

    return GreenCorridorRecommendResponse(
        corridor_plan=GreenCorridorPlanResponse(
            corridor_id=plan.corridor_id,
            path=plan.path,
            signal_actions=[
                CorridorSignalActionResponse(
                    intersection_id=sa.intersection_id,
                    signal_id=sa.signal_id,
                    action=sa.action,
                    duration_seconds=sa.duration_seconds,
                    reason=sa.reason,
                )
                for sa in plan.signal_actions
            ],
            estimated_minutes=round(plan.estimated_minutes, 3),
            from_intersection_id=plan.from_intersection_id,
            to_intersection_id=plan.to_intersection_id,
        ),
        is_recommendation=True,
        note="Advisory recommendation only; no database changes or signal actuations executed.",
    )


# ==============================================================================
# 6. GET /decisions, GET /decisions/{id}, POST /decisions/{id}/apply, /revert
# ==============================================================================


@router.get(
    "/decisions",
    response_model=PaginatedDecisionsResponse,
    status_code=status.HTTP_200_OK,
    summary="Query advisory control decision history with pagination (analyst+)",
)
async def get_decisions(
    intersection_id: Optional[int] = Query(None, description="Optional intersection identifier filter"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    per_page: int = Query(50, ge=1, le=100, description="Records per page (1-100)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> PaginatedDecisionsResponse:
    """Retrieve historical advisory decisions ordered newest-first with pagination."""
    count_stmt = select(func.count(AIDecision.id))
    if intersection_id is not None:
        count_stmt = count_stmt.where(AIDecision.intersection_id == intersection_id)
    total_res = await db.execute(count_stmt)
    total = int(total_res.scalar() or 0)

    pages = math.ceil(total / per_page) if total > 0 else 1
    offset = (page - 1) * per_page
    items = await DecisionStore.get_history(
        session=db,
        intersection_id=intersection_id,
        limit=per_page,
        offset=offset,
    )

    return PaginatedDecisionsResponse(
        items=[
            DecisionItemResponse(
                id=d.id,
                intersection_id=d.intersection_id,
                decision_type=d.decision_type,
                payload=d.payload if isinstance(d.payload, dict) else {},
                status=d.status,
                applied_by=d.applied_by,
                applied_at=d.applied_at,
                rationale=d.rationale,
                created_at=d.created_at,
                updated_at=d.updated_at,
            )
            for d in items
        ],
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
    )


@router.get(
    "/decisions/{id}",
    response_model=DecisionItemResponse,
    status_code=status.HTTP_200_OK,
    summary="Get single advisory control decision with full payload (analyst+)",
)
async def get_decision(
    id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> DecisionItemResponse:
    """Retrieve a single advisory control decision by primary key identifier."""
    stmt = select(AIDecision).where(AIDecision.id == id)
    res = await db.execute(stmt)
    decision = res.scalar_one_or_none()
    if decision is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"AIDecision with id {id} not found.",
        )
    return DecisionItemResponse(
        id=decision.id,
        intersection_id=decision.intersection_id,
        decision_type=decision.decision_type,
        payload=decision.payload if isinstance(decision.payload, dict) else {},
        status=decision.status,
        applied_by=decision.applied_by,
        applied_at=decision.applied_at,
        rationale=decision.rationale,
        created_at=decision.created_at,
        updated_at=decision.updated_at,
    )


@router.post(
    "/decisions/{id}/apply",
    response_model=DecisionItemResponse,
    status_code=status.HTTP_200_OK,
    summary="Transition proposed decision to applied status (officer/admin)",
)
async def apply_decision(
    id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> DecisionItemResponse:
    """Supervisory human approval transitioning decision status from proposed to applied."""
    try:
        updated = await DecisionStore.transition(
            session=db,
            decision_id=id,
            new_status="applied",
            user_id=current_user.id,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="control.decision_applied",
        actor_user_id=current_user.id,
        entity_type="ai_decision",
        entity_id=updated.id,
        details={
            "status": updated.status,
            "intersection_id": updated.intersection_id,
            "decision_type": updated.decision_type,
        },
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(updated)

    return DecisionItemResponse(
        id=updated.id,
        intersection_id=updated.intersection_id,
        decision_type=updated.decision_type,
        payload=updated.payload if isinstance(updated.payload, dict) else {},
        status=updated.status,
        applied_by=updated.applied_by,
        applied_at=updated.applied_at,
        rationale=updated.rationale,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
    )


@router.post(
    "/decisions/{id}/revert",
    response_model=DecisionItemResponse,
    status_code=status.HTTP_200_OK,
    summary="Revert decision status to reverted (officer/admin)",
)
async def revert_decision(
    id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> DecisionItemResponse:
    """Supervisory action reverting a proposed or applied decision back to reverted status."""
    try:
        updated = await DecisionStore.transition(
            session=db,
            decision_id=id,
            new_status="reverted",
            user_id=current_user.id,
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="control.decision_reverted",
        actor_user_id=current_user.id,
        entity_type="ai_decision",
        entity_id=updated.id,
        details={
            "status": updated.status,
            "intersection_id": updated.intersection_id,
            "decision_type": updated.decision_type,
        },
        ip_address=client_ip,
    )
    await db.commit()
    await db.refresh(updated)

    return DecisionItemResponse(
        id=updated.id,
        intersection_id=updated.intersection_id,
        decision_type=updated.decision_type,
        payload=updated.payload if isinstance(updated.payload, dict) else {},
        status=updated.status,
        applied_by=updated.applied_by,
        applied_at=updated.applied_at,
        rationale=updated.rationale,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
    )


# ==============================================================================
# 7. GET /junctions/{intersection_id}/control-status
# ==============================================================================


@router.get(
    "/junctions/{intersection_id}/control-status",
    response_model=JunctionControlStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve real-time supervisory control status for an intersection",
)
async def get_junction_control_status(
    intersection_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> JunctionControlStatusResponse:
    """Retrieve operational control telemetry, incidents, emergency status, and latest decision.

    Guarantees:
    - Verifies intersection existence (404 otherwise).
    - Queries latest telemetry age, optical signal state, open incidents, and emergency vehicle status.
    - Queries latest emitted AIDecision and latest AIPrediction without N+1 query overhead.
    """
    # 1. Verify intersection exists
    inter_stmt = select(Intersection.id).where(Intersection.id == intersection_id)
    inter_res = await db.execute(inter_stmt)
    if inter_res.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Intersection {intersection_id} not found.",
        )

    # 2. Latest telemetry age
    record_stmt = (
        select(TrafficRecord.recorded_at)
        .where(TrafficRecord.intersection_id == intersection_id)
        .order_by(TrafficRecord.recorded_at.desc(), TrafficRecord.id.desc())
        .limit(1)
    )
    rec_res = await db.execute(record_stmt)
    rec_time = rec_res.scalar_one_or_none()
    latest_telemetry_age_s: Optional[float] = None
    if rec_time is not None:
        now = datetime.now(timezone.utc)
        if rec_time.tzinfo is None:
            rec_time = rec_time.replace(tzinfo=timezone.utc)
        latest_telemetry_age_s = round(max(0.0, (now - rec_time).total_seconds()), 2)

    # 3. Current observed optical signal state
    sig_stmt = (
        select(Signal.observed_state)
        .where(Signal.intersection_id == intersection_id)
        .order_by(
            Signal.observed_at.desc().nullslast(),
            Signal.updated_at.desc(),
            Signal.id.desc(),
        )
        .limit(1)
    )
    sig_res = await db.execute(sig_stmt)
    current_observed_signal_state = sig_res.scalar_one_or_none()

    # 4. Open incidents count
    inc_stmt = (
        select(func.count(Incident.id))
        .where(
            Incident.intersection_id == intersection_id,
            Incident.status != "resolved",
        )
    )
    inc_res = await db.execute(inc_stmt)
    open_incidents_count = int(inc_res.scalar() or 0)

    # 5. Active emergency vehicle presence nearby
    road_stmt = select(Road.from_intersection_id, Road.to_intersection_id).where(
        (Road.from_intersection_id == intersection_id)
        | (Road.to_intersection_id == intersection_id)
    )
    road_res = await db.execute(road_stmt)
    nearby_junctions = {intersection_id}
    for f_id, t_id in road_res.all():
        if f_id is not None:
            nearby_junctions.add(f_id)
        if t_id is not None:
            nearby_junctions.add(t_id)

    em_stmt = (
        select(func.count(EmergencyEvent.id))
        .select_from(EmergencyEvent)
        .join(Incident, EmergencyEvent.incident_id == Incident.id)
        .where(
            Incident.intersection_id.in_(list(nearby_junctions)),
            EmergencyEvent.status.in_(["active", "dispatched", "on_scene"]),
            EmergencyEvent.status != "resolved",
        )
    )
    em_res = await db.execute(em_stmt)
    active_emergency = bool((em_res.scalar() or 0) > 0)

    # 6. Latest decision
    dec_stmt = (
        select(AIDecision)
        .where(AIDecision.intersection_id == intersection_id)
        .order_by(AIDecision.created_at.desc(), AIDecision.id.desc())
        .limit(1)
    )
    dec_res = await db.execute(dec_stmt)
    latest_dec = dec_res.scalar_one_or_none()
    latest_decision_summary: Optional[LatestDecisionSummary] = None
    if latest_dec is not None:
        latest_decision_summary = LatestDecisionSummary(
            id=latest_dec.id,
            action=latest_dec.decision_type,
            created_at=latest_dec.created_at,
            reason=latest_dec.rationale,
        )

    # 7. Latest congestion prediction
    pred_stmt = (
        select(AIPrediction)
        .where(
            AIPrediction.intersection_id == intersection_id,
            AIPrediction.prediction_type == "congestion",
        )
        .order_by(AIPrediction.created_at.desc(), AIPrediction.id.desc())
        .limit(1)
    )
    pred_res = await db.execute(pred_stmt)
    latest_pred = pred_res.scalar_one_or_none()
    latest_pred_summary: Optional[LatestPredictionSummary] = None
    if latest_pred is not None:
        cong_val: Optional[float] = None
        if isinstance(latest_pred.payload, dict):
            raw_cong = latest_pred.payload.get("congestion") or latest_pred.payload.get("value")
            if raw_cong is not None:
                try:
                    cong_val = float(raw_cong)
                except (ValueError, TypeError):
                    pass
        latest_pred_summary = LatestPredictionSummary(
            congestion=cong_val,
            model_version=latest_pred.model_version,
            predicted_for=latest_pred.predicted_for,
            confidence=latest_pred.confidence,
        )

    return JunctionControlStatusResponse(
        intersection_id=intersection_id,
        latest_telemetry_age_s=latest_telemetry_age_s,
        current_observed_signal_state=current_observed_signal_state,
        open_incidents_count=open_incidents_count,
        active_emergency=active_emergency,
        latest_decision=latest_decision_summary,
        latest_prediction=latest_pred_summary,
    )
