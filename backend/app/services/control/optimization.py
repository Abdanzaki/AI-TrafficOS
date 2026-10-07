"""Queue-proportional signal timing optimization service (Phase 6 Part 2).

CRITICAL ARCHITECTURAL SAFETY INVARIANT:
----------------------------------------
This optimization engine is strictly advisory, supervisory, and non-actuating.
All timings calculated by this module are proposals (`is_recommendation=True`).
The system NEVER directly commands hardware signal controllers or overrides
field conflict monitor units (CMUs/MMUs).

WEBSTER-INSPIRED QUEUE-PROPORTIONAL ALLOCATION MATHEMATICS:
------------------------------------------------------------
In classic traffic engineering (F.V. Webster, "Traffic Signal Settings", Road
Research Technical Paper No. 39, 1958), the theoretical optimum cycle time $C_0$
minimizing aggregate vehicle delay across all approaches is formulated as:

    C_0 = (1.5 * L + 5) / (1 - Y)

where:
  - $L$ is total lost time per cycle: the sum of transition clearance intervals
    across all phases, L = sum(yellow_i + all_red_i).
  - $Y$ is the sum of critical movement flow ratios: Y = sum(y_i) = sum(q_i / s_i),
    where $q_i$ is approach volume and $s_i$ is saturation flow rate.

In real-time queue-proportional adaptive control (drawing on Webster split
allocation and adaptive philosophies such as SCATS/SCOOT):
1. Per-Phase Composite Demand Score ($D_i$):
   Physical queue length is combined with lane density, predictive queue dynamics,
   and forecast congestion intensity using defensible, empirical scaling constants:

       D_i = queue_length_i
             + density_i * lane_count_i * K1
             + max(0, predicted_queue_growth_i) * K2
             + predicted_congestion_i * K3

   Tunable empirical scaling weights:
     - K1 = 8.0: Lane density storage weight. Converts approach vehicle packing density
       [0.0, 1.0] across active lane count into equivalent queued vehicle units.
     - K2 = 2.0: Predictive queue growth rate weight. Scales forecast queue buildup
       (veh/min) to preemptively allocate green before stop-bar queues spill over.
     - K3 = 10.0: Predictive horizon congestion weight. Maps forecast congestion
       intensity [0.0, 1.0] to equivalent queue backlog pressure.

2. Emergency Route Priority Bump:
   Phases serving designated emergency vehicle routes receive a documented +50%
   demand boost:
       D_i <- D_i * 1.5
   This biases the discretionary split toward emergency progression corridors
   while preserving clearance intervals and safety timing boundaries.

3. Target Cycle Length Budgeting:
   Fixed cycle overhead (minimum green + yellow + all-red per phase):
       T_fixed = n_phases * (min_green_s + yellow_s + all_red_s)
   Target adaptive cycle length expands with cumulative junction demand:
       C_target = min(180.0, T_fixed + total_demand * 1.5)
   where 180s represents the maximum permissible urban cycle length to prevent
   excessive cross-street delay. Available discretionary green budget:
       Budget = max(0.0, C_target - T_fixed)

4. Proportional Split Allocation:
   If total demand across all phases is zero (total_demand == 0):
       green_i = min_green_s  (for all i, with note 'no demand')
   Otherwise, the discretionary green budget is distributed in proportion to demand:
       green_i = min_green_s + (D_i / total_demand) * Budget
   Each green allocation is strictly clamped within statutory bounds:
       green_i = max(min_green_s, min(max_green_s, green_i))

5. Purity and Determinism:
   This module provides pure, side-effect-free calculation functions.
   No database access, network calls, or random generators are involved.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# Tunable empirical scaling constants (documented above)
K1_DENSITY_WEIGHT: float = 8.0
K2_QUEUE_GROWTH_WEIGHT: float = 2.0
K3_PREDICTED_CONGESTION_WEIGHT: float = 10.0
EMERGENCY_PRIORITY_MULTIPLIER: float = 1.5
MAX_CYCLE_TIME_S: float = 180.0


@dataclass(frozen=True)
class CycleConfig:
    """Operational cycle timing boundaries and transition intervals.

    Attributes:
        min_green_s: Statutory minimum green interval in seconds (default 7.0s).
            Ensures driver perception-reaction time and minimum pedestrian clearance.
        max_green_s: Maximum permissible green interval in seconds (default 60.0s).
            Prevents unserviced cross-street starvation and driver red-light violations.
        yellow_s: Yellow change interval in seconds (default 3.0s).
            Clears vehicles in dilemma zones prior to red indication.
        all_red_s: All-red clearance interval in seconds (default 2.0s).
            Ensures the conflict area is vacant before opposing right-of-way starts.
    """

    min_green_s: float = 7.0
    max_green_s: float = 60.0
    yellow_s: float = 3.0
    all_red_s: float = 2.0

    def __post_init__(self) -> None:
        """Validate safety constraints on configuration intervals."""
        if self.min_green_s <= 0:
            raise ValueError(f"min_green_s must be positive, got {self.min_green_s}")
        if self.max_green_s < self.min_green_s:
            raise ValueError(
                f"max_green_s ({self.max_green_s}) must be >= min_green_s ({self.min_green_s})"
            )
        if self.yellow_s < 0:
            raise ValueError(f"yellow_s must be non-negative, got {self.yellow_s}")
        if self.all_red_s < 0:
            raise ValueError(f"all_red_s must be non-negative, got {self.all_red_s}")


@dataclass
class PhaseDemand:
    """Observed and predicted demand telemetry for a specific signal phase.

    Attributes:
        phase_id: Unique database identifier of the signal phase.
        phase_name: Human-readable movement designation (e.g. 'NB_THRU', 'SB_LEFT').
        queue_length: Stop-bar vehicle queue count in vehicles.
        density: Normalized approach lane density in range [0.0, 1.0].
        flow_veh_per_min: Measured approach flow rate in vehicles per minute.
        predicted_congestion: Optional forecast congestion metric normalized in [0.0, 1.0].
        predicted_queue_growth: Optional forecast queue growth rate in vehicles per minute.
        lane_count: Number of approach lanes allocated to this phase (default 1).
        is_emergency_route: Flag indicating phase belongs to an active emergency corridor.
    """

    phase_id: int
    phase_name: str
    queue_length: float
    density: float
    flow_veh_per_min: float
    predicted_congestion: Optional[float] = None
    predicted_queue_growth: Optional[float] = None
    lane_count: int = 1
    is_emergency_route: bool = False


@dataclass
class OptimizationResult:
    """Calculated signal timing recommendation and diagnostic breakdown.

    Attributes:
        recommended_green_s: Mapping of phase_id to recommended green duration in seconds.
        total_cycle_s: Total cycle duration in seconds (sum of greens + clearances).
        method: Identifier of the algorithmic strategy utilized.
        inputs_echo: Echoed composite demand scores keyed by phase_id.
        computed_at: Generation timestamp in UTC.
        note: Optional diagnostic message or fallback justification.
    """

    recommended_green_s: dict[int, float]
    total_cycle_s: float
    method: str = "queue_proportional_webster_inspired"
    inputs_echo: dict[int, float] = field(default_factory=dict)
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    note: Optional[str] = None


class _class_or_instancemethod:
    """Descriptor enabling a method to be called either on an instance or on the class directly."""

    def __init__(self, func: Any) -> None:
        self.func = func

    def __get__(self, obj: Any, cls: Any = None) -> Any:
        if obj is None:
            obj = cls()
        return self.func.__get__(obj, cls)


class SignalOptimizer:
    """Deterministic, pure signal timing optimization engine.

    Calculates queue-proportional green allocations conforming to Webster-inspired
    adaptive principles.
    """

    def __init__(
        self,
        k1: float = K1_DENSITY_WEIGHT,
        k2: float = K2_QUEUE_GROWTH_WEIGHT,
        k3: float = K3_PREDICTED_CONGESTION_WEIGHT,
        emergency_priority_multiplier: float = EMERGENCY_PRIORITY_MULTIPLIER,
        max_target_cycle_s: float = MAX_CYCLE_TIME_S,
    ) -> None:
        """Initialize optimizer with tunable demand scoring parameters.

        Args:
            k1: Density weight scaling approach occupancy to queue equivalents (default 8.0).
            k2: Predictive queue growth scaling factor (default 2.0).
            k3: Predictive congestion intensity scaling factor (default 10.0).
            emergency_priority_multiplier: Multiplier applied to emergency route demand (default 1.5).
            max_target_cycle_s: Upper bound for target cycle time (default 180.0s).
        """
        self.k1 = k1
        self.k2 = k2
        self.k3 = k3
        self.emergency_priority_multiplier = emergency_priority_multiplier
        self.max_target_cycle_s = max_target_cycle_s

    @_class_or_instancemethod
    def compute_phase_demand_score(self, demand: PhaseDemand) -> float:
        """Calculate composite demand score for a single approach phase.

        Formula:
            score = queue_length
                  + density * lane_count * K1
                  + max(0, predicted_queue_growth) * K2
                  + predicted_congestion * K3

        If `is_emergency_route` is True, score is boosted by +50% (multiplied by 1.5).

        Args:
            demand: Telemetry snapshot for the phase.

        Returns:
            Non-negative composite demand score.
        """
        queue = max(0.0, float(demand.queue_length))
        density = max(0.0, min(1.0, float(demand.density)))
        lanes = max(1, int(demand.lane_count))

        growth = 0.0
        if demand.predicted_queue_growth is not None:
            growth = max(0.0, float(demand.predicted_queue_growth))

        congestion = 0.0
        if demand.predicted_congestion is not None:
            # Handle normalized [0.0, 1.0] inputs defensively
            congestion = max(0.0, min(1.0, float(demand.predicted_congestion)))

        score = (
            queue
            + (density * lanes * self.k1)
            + (growth * self.k2)
            + (congestion * self.k3)
        )

        if demand.is_emergency_route:
            score *= self.emergency_priority_multiplier

        return max(0.0, round(score, 4))

    @_class_or_instancemethod
    def optimize(
        self,
        demands: list[PhaseDemand],
        current_phase_id: Optional[int] = None,
        cycle_config: Optional[CycleConfig] = None,
    ) -> OptimizationResult:
        """Allocate green splits proportionally based on composite approach demand.

        Deterministic Webster-inspired green distribution:
        - Target cycle length scales with total junction demand up to 180 seconds.
        - Fixed clearance lost time (yellow + all-red) and base minimum green are guaranteed.
        - Surplus green budget is partitioned according to relative phase demand.
        - Every allocation is clamped strictly within [min_green_s, max_green_s].
        - If total demand is zero, all phases receive minimum green with note 'no demand'.

        Args:
            demands: List of PhaseDemand items for all approaches at the intersection.
            current_phase_id: Optional ID of the currently active green phase.
            cycle_config: Cycle boundaries and clearance intervals (defaults to CycleConfig()).

        Returns:
            OptimizationResult containing per-phase green seconds, total cycle, and demand echo.
        """
        if cycle_config is None:
            cycle_config = CycleConfig()

        now = datetime.now(timezone.utc)
        n_phases = len(demands)

        # Edge case: No phases provided
        if n_phases == 0:
            return OptimizationResult(
                recommended_green_s={},
                total_cycle_s=0.0,
                method="queue_proportional_webster_inspired",
                inputs_echo={},
                computed_at=now,
                note="no demand",
            )

        # 1. Compute per-phase demand scores
        demand_scores: dict[int, float] = {}
        for d in demands:
            demand_scores[d.phase_id] = self.compute_phase_demand_score(d)

        total_demand = sum(demand_scores.values())

        # 2. Case: Zero demand across all approaches
        if total_demand <= 0.0:
            rec_greens: dict[int, float] = {
                d.phase_id: float(cycle_config.min_green_s) for d in demands
            }
            fixed_clearance = n_phases * (cycle_config.yellow_s + cycle_config.all_red_s)
            total_cycle = sum(rec_greens.values()) + fixed_clearance
            return OptimizationResult(
                recommended_green_s=rec_greens,
                total_cycle_s=round(total_cycle, 2),
                method="queue_proportional_webster_inspired",
                inputs_echo=demand_scores,
                computed_at=now,
                note="no demand",
            )

        # 3. Non-zero demand: calculate target cycle and available green budget
        min_cycle_fixed = n_phases * (
            cycle_config.min_green_s + cycle_config.yellow_s + cycle_config.all_red_s
        )
        target_cycle = min(
            self.max_target_cycle_s,
            min_cycle_fixed + (total_demand * 1.5),
        )
        budget = max(0.0, target_cycle - min_cycle_fixed)

        # 4. Allocate green time proportionally and clamp to [min_green_s, max_green_s]
        recommended_green_s: dict[int, float] = {}
        for d in demands:
            p_score = demand_scores[d.phase_id]
            raw_green = cycle_config.min_green_s + (p_score / total_demand) * budget
            clamped_green = max(
                float(cycle_config.min_green_s),
                min(float(cycle_config.max_green_s), raw_green),
            )
            recommended_green_s[d.phase_id] = round(clamped_green, 2)

        # 5. Calculate real aggregate cycle time after clamping
        total_clearance = n_phases * (cycle_config.yellow_s + cycle_config.all_red_s)
        total_cycle_s = sum(recommended_green_s.values()) + total_clearance

        return OptimizationResult(
            recommended_green_s=recommended_green_s,
            total_cycle_s=round(total_cycle_s, 2),
            method="queue_proportional_webster_inspired",
            inputs_echo=demand_scores,
            computed_at=now,
            note=None,
        )
