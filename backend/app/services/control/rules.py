"""Deterministic priority-ordered control rule evaluation services (Phase 6 Part 3).

CRITICAL ARCHITECTURAL SAFETY INVARIANT:
----------------------------------------
This module defines deterministic, advisory rule evaluation logic for traffic signal control.
All decisions emitted by these rules are recommendations (`is_recommendation=True`).
The system NEVER directly actuates physical hardware, overrides conflict monitor units (MMUs/CMUs),
or operates without supervisory guardrails.
"""

from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.signal import Signal
from app.services.control.schemas import (
    Decision,
    DecisionAction,
    PredictedState,
    TrafficState,
)

# ==============================================================================
# Tunable Operational Default Thresholds
# ==============================================================================
# NOTE: The thresholds below represent tunable operational defaults calibrated
# for representative urban arterial junctions. They are NOT universal traffic-engineering
# absolutes and should be tuned per municipal signal timing policy and approach geometry.

# QUEUE_LENGTH_REROUTE_THRESHOLD:
# Stop-bar queue length (passenger car equivalents) representing severe localized approach
# congestion where signal split extensions alone cannot dissipate queue spillback without
# blocking upstream junctions or left-turn bays. Recommends upstream traffic rerouting.
QUEUE_LENGTH_REROUTE_THRESHOLD: float = 25.0

# QUEUE_GROWTH_REROUTE_THRESHOLD:
# Forecast queue expansion rate (vehicles per minute) from predictive machine learning models.
# A growth rate exceeding 2.0 veh/min signals rapid impending saturation where arrival flow rate
# significantly outstrips approach discharge capacity, justifying upstream traffic diversion.
QUEUE_GROWTH_REROUTE_THRESHOLD: float = 2.0

# QUEUE_LENGTH_EXTEND_GREEN_THRESHOLD:
# Stop-bar queue length representing moderate congestion where extending the active green split
# within statutory safety bounds can discharge the queue within the current cycle.
QUEUE_LENGTH_EXTEND_GREEN_THRESHOLD: float = 15.0

# DENSITY_REDUCE_GREEN_THRESHOLD:
# Normalized traffic density threshold [0.0, 1.0] below which approach green time is largely
# underutilized, indicating sparse vehicular arrivals.
DENSITY_REDUCE_GREEN_THRESHOLD: float = 0.15

# QUEUE_LENGTH_REDUCE_GREEN_THRESHOLD:
# Minimal residual stop-bar queue (vehicles) where early green phase termination frees
# cycle capacity to service waiting cross-street movements without inducing approach delay.
QUEUE_LENGTH_REDUCE_GREEN_THRESHOLD: float = 3.0

# ==============================================================================
# Rule-Based Decision Confidence Standards
# ==============================================================================
# Calibrated confidence scores reflecting algorithmic certainty for rule-derived actions.
CONFIDENCE_EMERGENCY: float = 0.9
CONFIDENCE_REROUTE_DEFAULT: float = 0.7
CONFIDENCE_SPLIT_ADJUSTMENT: float = 0.65


async def query_signals_for_intersection(
    session: AsyncSession,
    intersection_id: int,
) -> list[int]:
    """Query real signal controller IDs installed at the specified intersection.

    Args:
        session: Active asynchronous SQLAlchemy session.
        intersection_id: Identifier of the junction.

    Returns:
        List of primary key signal IDs ordered ascending.
    """
    stmt = (
        select(Signal.id)
        .where(Signal.intersection_id == intersection_id)
        .order_by(Signal.id.asc())
    )
    res = await session.execute(stmt)
    return list(res.scalars().all())


def evaluate_control_rules(
    state: TrafficState,
    predicted: Optional[PredictedState] = None,
    affected_signal_ids: Optional[Sequence[int]] = None,
) -> Decision:
    """Evaluate deterministic, priority-ordered supervisory traffic control rules.

    Priority Hierarchy:
    1. Active Emergency Preemption: If state.active_emergency -> PRIORITIZE_EMERGENCY
       (confidence 0.9; cites emergency; targets junction signals).
    2. Impending Saturation Reroute: If queue >= 25 and predicted queue_growth > 2.0 -> REROUTE_TRAFFIC
       (cites queue + growth + model version; confidence from predicted model or default 0.7).
    3. Approach Queue Split Extension: If queue >= 15 -> EXTEND_GREEN
       (confidence 0.65; expected impact 'reduce queue by serving the loaded approach longer').
    4. Low-Demand Split Truncation: If density <= 0.15 and queue <= 3 -> REDUCE_GREEN
       (confidence 0.65; reason 'low demand — reallocate green time'; expected impact 'shorter cycle, less cross-traffic wait').
    5. Nominal Baseline Conditions: Else -> NO_ACTION
       (reason 'conditions within normal bounds'; confidence None).

    Args:
        state: Valid, observed physical TrafficState snapshot.
        predicted: Optional predictive forecast horizon context.
        affected_signal_ids: Real signal IDs at intersection subject to timing adjustment.

    Returns:
        Advisory Decision recommendation guaranteed to have is_recommendation=True.
    """
    signals = list(affected_signal_ids) if affected_signal_ids is not None else []

    # Rule 1: Emergency preemption takes highest operational precedence
    if state.active_emergency:
        return Decision(
            intersection_id=state.intersection_id,
            action=DecisionAction.PRIORITIZE_EMERGENCY,
            current=state,
            predicted=predicted,
            reason=(
                f"Active emergency transit detected at intersection {state.intersection_id}; "
                "prioritizing emergency vehicle progression."
            ),
            expected_impact="Preempt conflicting movements to provide continuous right-of-way for emergency responders.",
            confidence=CONFIDENCE_EMERGENCY,
            affected_signal_ids=signals,
            model_version=predicted.model_version if predicted else None,
            is_recommendation=True,
        )

    # Rule 2: Impending saturation and severe queue growth triggers upstream diversion
    if (
        state.queue_length >= QUEUE_LENGTH_REROUTE_THRESHOLD
        and predicted is not None
        and predicted.queue_growth > QUEUE_GROWTH_REROUTE_THRESHOLD
    ):
        model_ver = predicted.model_version or "unknown"
        reroute_confidence = (
            predicted.confidence
            if predicted.confidence is not None
            else CONFIDENCE_REROUTE_DEFAULT
        )
        return Decision(
            intersection_id=state.intersection_id,
            action=DecisionAction.REROUTE_TRAFFIC,
            current=state,
            predicted=predicted,
            reason=(
                f"Queue length ({state.queue_length:.1f} veh >= {QUEUE_LENGTH_REROUTE_THRESHOLD:.1f}) "
                f"and predicted queue growth ({predicted.queue_growth:.2f} > {QUEUE_GROWTH_REROUTE_THRESHOLD:.2f}) "
                f"exceed threshold under model {model_ver}; recommend upstream detour."
            ),
            expected_impact="Divert upstream vehicular flow to parallel arterials to prevent junction gridlock.",
            confidence=reroute_confidence,
            affected_signal_ids=signals,
            model_version=predicted.model_version,
            is_recommendation=True,
        )

    # Rule 3: Heavy queue on running approach calls for green split extension
    if state.queue_length >= QUEUE_LENGTH_EXTEND_GREEN_THRESHOLD:
        return Decision(
            intersection_id=state.intersection_id,
            action=DecisionAction.EXTEND_GREEN,
            current=state,
            predicted=predicted,
            reason=(
                f"Queue length ({state.queue_length:.1f} veh >= {QUEUE_LENGTH_EXTEND_GREEN_THRESHOLD:.1f} veh) "
                "exceeds threshold; split extension recommended."
            ),
            expected_impact="reduce queue by serving the loaded approach longer",
            confidence=CONFIDENCE_SPLIT_ADJUSTMENT,
            affected_signal_ids=signals,
            model_version=predicted.model_version if predicted else None,
            is_recommendation=True,
        )

    # Rule 4: Sparse approach demand allows green split truncation
    if (
        state.density <= DENSITY_REDUCE_GREEN_THRESHOLD
        and state.queue_length <= QUEUE_LENGTH_REDUCE_GREEN_THRESHOLD
    ):
        return Decision(
            intersection_id=state.intersection_id,
            action=DecisionAction.REDUCE_GREEN,
            current=state,
            predicted=predicted,
            reason="low demand — reallocate green time",
            expected_impact="shorter cycle, less cross-traffic wait",
            confidence=CONFIDENCE_SPLIT_ADJUSTMENT,
            affected_signal_ids=signals,
            model_version=predicted.model_version if predicted else None,
            is_recommendation=True,
        )

    # Rule 5: Nominal baseline operating conditions
    return Decision(
        intersection_id=state.intersection_id,
        action=DecisionAction.NO_ACTION,
        current=state,
        predicted=predicted,
        reason="conditions within normal bounds",
        expected_impact="Maintain current signal timing and phase progression.",
        confidence=None,
        affected_signal_ids=[],
        model_version=predicted.model_version if predicted else None,
        is_recommendation=True,
    )
