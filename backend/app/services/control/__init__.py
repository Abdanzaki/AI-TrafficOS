"""Intelligent Traffic Control service package (Phase 6).

CRITICAL ARCHITECTURAL SAFETY INVARIANT:
----------------------------------------
This package provides advisory and supervisory decision models.
All decisions emitted by this engine are recommendations (`is_recommendation=True`).
The system NEVER claims direct hardware controller actuation, overrides local
conflict monitors, or bypasses physical failsafes. All actions are submitted as
proposals requiring human supervisory approval or compliant NTCIP field translation.
"""

from app.services.control.decisions import DecisionEngine, TrafficStateBuilder
from app.services.control.emergency import (
    EmergencyDecision,
    EmergencyPriorityOrchestrator,
)
from app.services.control.exceptions import (
    InsufficientDataError,
    StaleTelemetryError,
    UnsafeStateError,
)
from app.services.control.hardware import (
    PhysicalHardwareControlDisabledError,
    assert_physical_hardware_disabled,
    dispatch_hardware_signal_command,
)
from app.services.control.optimization import (
    CycleConfig,
    OptimizationResult,
    PhaseDemand,
    SignalOptimizer,
)
from app.services.control.persistence import DecisionStore
from app.services.control.rules import (
    CONFIDENCE_EMERGENCY,
    CONFIDENCE_REROUTE_DEFAULT,
    CONFIDENCE_SPLIT_ADJUSTMENT,
    DENSITY_REDUCE_GREEN_THRESHOLD,
    QUEUE_GROWTH_REROUTE_THRESHOLD,
    QUEUE_LENGTH_EXTEND_GREEN_THRESHOLD,
    QUEUE_LENGTH_REDUCE_GREEN_THRESHOLD,
    QUEUE_LENGTH_REROUTE_THRESHOLD,
    evaluate_control_rules,
    query_signals_for_intersection,
)
from app.services.control.safety import (
    SafetyValidator,
    ValidatedPlan,
)
from app.services.control.schemas import (
    Decision,
    DecisionAction,
    PredictedState,
    TrafficState,
)
from app.services.control.simulation import (
    ApproachSimulationResult,
    ApproachState,
    PlanComparison,
    SignalPlan,
    SimulationConfig,
    SimulationResult,
    WhatIfSimulator,
    compute_plan_digest,
)

__all__ = [
    # Schemas & Enumerations
    "DecisionAction",
    "TrafficState",
    "PredictedState",
    "Decision",
    # Engine & State Construction
    "TrafficStateBuilder",
    "DecisionEngine",
    # Emergency Priority Orchestration (Phase 6 Part 3)
    "EmergencyDecision",
    "EmergencyPriorityOrchestrator",
    # Rule Evaluation & Thresholds (Phase 6 Part 3)
    "evaluate_control_rules",
    "query_signals_for_intersection",
    "QUEUE_LENGTH_REROUTE_THRESHOLD",
    "QUEUE_GROWTH_REROUTE_THRESHOLD",
    "QUEUE_LENGTH_EXTEND_GREEN_THRESHOLD",
    "DENSITY_REDUCE_GREEN_THRESHOLD",
    "QUEUE_LENGTH_REDUCE_GREEN_THRESHOLD",
    "CONFIDENCE_EMERGENCY",
    "CONFIDENCE_REROUTE_DEFAULT",
    "CONFIDENCE_SPLIT_ADJUSTMENT",
    # Optimization (Phase 6 Part 2)
    "CycleConfig",
    "PhaseDemand",
    "OptimizationResult",
    "SignalOptimizer",
    # Safety Validation (Phase 6 Part 2)
    "ValidatedPlan",
    "SafetyValidator",
    # Persistence Store
    "DecisionStore",
    # What-If Simulation (Phase 6 Part 4)
    "ApproachState",
    "SignalPlan",
    "SimulationConfig",
    "ApproachSimulationResult",
    "SimulationResult",
    "PlanComparison",
    "WhatIfSimulator",
    "compute_plan_digest",
    # Exceptions & Guards
    "StaleTelemetryError",
    "InsufficientDataError",
    "UnsafeStateError",
    "PhysicalHardwareControlDisabledError",
    "assert_physical_hardware_disabled",
    "dispatch_hardware_signal_command",
]
