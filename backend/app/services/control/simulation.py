"""Lightweight, deterministic point-queue traffic simulator for signal plan comparison (Phase 6 Part 4).

MODEL CLASSIFICATION:
---------------------
Store-and-forward / macroscopic point-queue model per intersection approach.

PHYSICAL ASSUMPTIONS:
---------------------
1. Uniform Arrival Dynamics: Arrivals arrive at a constant, uniform inflow rate
   (`arrival_rate_veh_per_min`) across the evaluation horizon. Transient platoon
   bursts and upstream coordination shockwaves are averaged over the discrete time-step.
2. Deterministic Service at Saturation Flow: During active green intervals, discharge
   proceeds deterministically at the approach saturation flow rate (`saturation_flow_veh_per_min`).
   Startup lost time and yellow clearance lost time are explicitly modeled via clearance intervals
   (`yellow_s` + `all_red_s`), during which right-of-way is cleared and departure rate is zero.
3. No Spillback Modeling: Approach queues are assumed to have unbounded physical storage
   capacity. Spillback blocking upstream intersections or de facto lane starvation is NOT modeled.
4. No Pedestrian Actuation: Pedestrian clearance phases and actuated detector extensions
   are omitted. The signal timing executes strictly as a cyclic fixed-time schedule.

ENGINEERING LIMITATIONS & APPLICABILITY:
----------------------------------------
This engine is a PLANNING-GRADE COMPARISON TOOL, NOT A MICROSIGNAL OR MICROSCOPIC
SIMULATOR (such as SUMO or VISSIM).
Results are comparative estimates intended for ranking and vetting candidate signal plans
relative to baseline operations, NOT exact forecasts of physical real-world outcomes.

CRITICAL ARCHITECTURAL REPORTING INVARIANT:
-------------------------------------------
Under NO CIRCUMSTANCES may this module or its comparison structures emit
percentage-improvement marketing language (e.g. "delivers 25% delay reduction",
"improves throughput by 40%").
The deterministic verdict ('proposed_better', 'current_better', 'equivalent') and raw
physical deltas (delta_wait in veh*min, delta_avg_queue in vehicles, delta_throughput in
vehicles) are the ONLY comparative claims permitted.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Any, Optional


@dataclass
class ApproachState:
    """Initial physical traffic state and geometry parameters for an approach.

    Attributes:
        approach_id: Unique approach identifier (e.g. 'NB_THRU', 'EB_APPROACH').
        queue_veh: Stop-bar queued vehicle count at the start of the horizon (>= 0).
        arrival_rate_veh_per_min: Uniform arrival demand in vehicles per minute (>= 0).
        saturation_flow_veh_per_min: Maximum discharge service rate during green in veh/min.
            Defaults to 30.0 * lane_count (equivalent to 1800 veh/hr/lane).
        lane_count: Number of approach lanes (default 1, >= 1).
        name: Optional human-readable approach label (defaults to approach_id).
    """

    approach_id: str
    queue_veh: float
    arrival_rate_veh_per_min: float
    saturation_flow_veh_per_min: Optional[float] = None
    lane_count: int = 1
    name: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate input ranges and assign lane-scaled default saturation flow."""
        if not self.approach_id and self.name:
            self.approach_id = self.name
        elif not self.approach_id:
            raise ValueError("approach_id cannot be empty")

        if self.name is None:
            self.name = self.approach_id

        if self.lane_count <= 0:
            raise ValueError(f"lane_count must be >= 1, got {self.lane_count}")

        if self.queue_veh < 0:
            raise ValueError(f"queue_veh cannot be negative, got {self.queue_veh}")

        if self.arrival_rate_veh_per_min < 0:
            raise ValueError(
                f"arrival_rate_veh_per_min cannot be negative, got {self.arrival_rate_veh_per_min}"
            )

        if self.saturation_flow_veh_per_min is None:
            self.saturation_flow_veh_per_min = 30.0 * float(self.lane_count)
        elif self.saturation_flow_veh_per_min <= 0:
            raise ValueError(
                f"saturation_flow_veh_per_min must be positive, got {self.saturation_flow_veh_per_min}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert ApproachState to a dictionary."""
        return asdict(self)


@dataclass
class SignalPlan:
    """Cyclic signal timing plan and phase-to-approach assignment specification.

    Attributes:
        phases: Mapping of phase_name to green interval duration in seconds.
        phase_to_approaches: Mapping of phase_name to list of approach_ids receiving green.
        yellow_s: Yellow change clearance interval in seconds (default 3.0, >= 0).
        all_red_s: All-red clearance interval in seconds (default 2.0, >= 0).
    """

    phases: dict[str, float]
    phase_to_approaches: dict[str, list[str]]
    yellow_s: float = 3.0
    all_red_s: float = 2.0

    def __post_init__(self) -> None:
        """Validate signal plan intervals and phase continuity."""
        if self.yellow_s < 0:
            raise ValueError(f"yellow_s cannot be negative, got {self.yellow_s}")
        if self.all_red_s < 0:
            raise ValueError(f"all_red_s cannot be negative, got {self.all_red_s}")
        if not self.phases:
            raise ValueError("phases cannot be empty; at least one phase required")

        for p_name, g_s in self.phases.items():
            if g_s <= 0:
                raise ValueError(
                    f"green_s for phase '{p_name}' must be positive, got {g_s}"
                )

        # Defensively ensure every phase exists in phase_to_approaches mapping
        for p_name in self.phases:
            if p_name not in self.phase_to_approaches:
                self.phase_to_approaches[p_name] = []

    def __getitem__(self, phase_name: str) -> float:
        """Access green interval duration for a given phase name."""
        return self.phases[phase_name]

    def __contains__(self, phase_name: object) -> bool:
        """Check whether phase name is configured in the plan."""
        return phase_name in self.phases

    @property
    def cycle_length_s(self) -> float:
        """Total cycle duration in seconds (sum of green splits + clearance lost time)."""
        lost_time_per_phase = self.yellow_s + self.all_red_s
        return sum(self.phases.values()) + (len(self.phases) * lost_time_per_phase)

    def to_dict(self) -> dict[str, Any]:
        """Convert SignalPlan to a JSON-serializable dictionary."""
        return {
            "phases": dict(self.phases),
            "phase_to_approaches": {k: list(v) for k, v in self.phase_to_approaches.items()},
            "yellow_s": self.yellow_s,
            "all_red_s": self.all_red_s,
            "cycle_length_s": self.cycle_length_s,
        }


@dataclass(frozen=True)
class SimulationConfig:
    """Tunable operational parameters for point-queue traffic simulation.

    Attributes:
        horizon_minutes: Evaluation horizon lookahead duration in minutes (default 15.0).
            Governs the cumulative interval over which queues and wait are measured.
        dt_seconds: Discrete simulation time-step in seconds (default 5.0).
            Governs the temporal resolution of arrival and departure dynamics.
    """

    horizon_minutes: float = 15.0
    dt_seconds: float = 5.0

    def __post_init__(self) -> None:
        """Validate positive horizon and time-step boundaries."""
        if self.horizon_minutes <= 0:
            raise ValueError(f"horizon_minutes must be positive, got {self.horizon_minutes}")
        if self.dt_seconds <= 0:
            raise ValueError(f"dt_seconds must be positive, got {self.dt_seconds}")
        if self.dt_seconds > self.horizon_minutes * 60:
            raise ValueError(
                f"dt_seconds ({self.dt_seconds}s) cannot exceed total horizon "
                f"({self.horizon_minutes * 60}s)"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert SimulationConfig to a dictionary."""
        return asdict(self)


def compute_plan_digest(plan: SignalPlan) -> str:
    """Compute a deterministic cryptographic SHA-256 digest of signal plan inputs.

    Args:
        plan: SignalPlan instance.

    Returns:
        Hexadecimal SHA-256 digest string for auditability and traceability.
    """
    serialized = {
        "phases": {k: round(float(v), 4) for k, v in sorted(plan.phases.items())},
        "phase_to_approaches": {
            k: sorted(list(v)) for k, v in sorted(plan.phase_to_approaches.items())
        },
        "yellow_s": round(float(plan.yellow_s), 4),
        "all_red_s": round(float(plan.all_red_s), 4),
    }
    encoded = json.dumps(serialized, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass
class ApproachSimulationResult:
    """Simulated performance metrics for an individual intersection approach.

    Attributes:
        approach_id: Identifier of the evaluated approach.
        total_wait_veh_min: Cumulative waiting delay in vehicle-minutes over horizon.
        avg_queue_veh: Time-averaged queued vehicle count across the horizon.
        max_queue_veh: Peak queued vehicle count observed at any time-step.
        throughput_veh: Total vehicles discharged through the approach over horizon.
        residual_queue_veh: Backlog of queued vehicles remaining at horizon end.
    """

    approach_id: str
    total_wait_veh_min: float
    avg_queue_veh: float
    max_queue_veh: float
    throughput_veh: float
    residual_queue_veh: float

    def __getitem__(self, item: str) -> Any:
        """Support dict-like key access for robust compatibility."""
        return getattr(self, item)

    def to_dict(self) -> dict[str, Any]:
        """Convert ApproachSimulationResult to a dictionary."""
        return asdict(self)


@dataclass
class SimulationResult:
    """Aggregate simulation outcome and diagnostic breakdown for a signal plan.

    Attributes:
        total_wait_veh_min: Sum of vehicle waiting delay across all approaches in veh*min.
        avg_queue_veh: Mean cumulative queue across all approaches over the horizon.
        max_queue_veh: Peak aggregate queue observed across the intersection at any step.
        throughput_veh: Total departed vehicles across all approaches over the horizon.
        residual_queue_veh: Aggregate vehicle backlog remaining at the end of the horizon.
        per_approach: Detailed per-approach simulation results keyed by approach_id.
        plan_digest: Cryptographic hash of the evaluated signal plan.
        horizon_minutes: Evaluation horizon duration in minutes.
        computed_at: Generation timestamp in UTC.
        notes: Informational or diagnostic flags (e.g. 'empty approaches', 'oversaturated').
    """

    total_wait_veh_min: float
    avg_queue_veh: float
    max_queue_veh: float
    throughput_veh: float
    residual_queue_veh: float
    per_approach: dict[str, ApproachSimulationResult]
    plan_digest: str
    horizon_minutes: float
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    notes: list[str] = field(default_factory=list)

    @property
    def total_wait_veh_s(self) -> float:
        """Cumulative waiting delay converted to vehicle-seconds."""
        return round(self.total_wait_veh_min * 60.0, 4)

    @property
    def note(self) -> Optional[str]:
        """Diagnostic note string joined by semicolons, or None if empty."""
        return "; ".join(self.notes) if self.notes else None

    def to_dict(self) -> dict[str, Any]:
        """Convert SimulationResult to a JSON-serializable dictionary."""
        return {
            "total_wait_veh_min": self.total_wait_veh_min,
            "avg_queue_veh": self.avg_queue_veh,
            "max_queue_veh": self.max_queue_veh,
            "throughput_veh": self.throughput_veh,
            "residual_queue_veh": self.residual_queue_veh,
            "per_approach": {k: v.to_dict() for k, v in self.per_approach.items()},
            "plan_digest": self.plan_digest,
            "horizon_minutes": self.horizon_minutes,
            "computed_at": self.computed_at.isoformat(),
            "notes": list(self.notes),
        }


@dataclass
class PlanComparison:
    """Rigorous, deterministic comparison between current and proposed signal timing plans.

    CRITICAL ARCHITECTURAL REPORTING INVARIANT:
    -------------------------------------------
    This comparison engine strictly computes physical deltas (proposed - current) and a
    deterministic verdict ('proposed_better', 'current_better', 'equivalent').
    Under NO CIRCUMSTANCES may this class or module emit percentage-improvement
    marketing language (e.g. 'reduces wait by 25%', '30% improvement').
    The verdict and raw physical deltas are the ONLY comparative claims permitted.

    Attributes:
        current_result: SimulationResult for the baseline / current signal plan.
        proposed_result: SimulationResult for the candidate / proposed signal plan.
        delta_wait: Difference in total wait time (proposed - current) in veh*min.
            Negative indicates proposed plan reduced aggregate delay.
        delta_avg_queue: Difference in mean queue length (proposed - current) in vehicles.
        delta_throughput: Difference in total departed volume (proposed - current) in vehicles.
        verdict: Deterministic outcome string: 'proposed_better', 'current_better', or 'equivalent'.
    """

    current_result: SimulationResult
    proposed_result: SimulationResult
    delta_wait: float
    delta_avg_queue: float
    delta_throughput: float
    verdict: str

    @property
    def delta_wait_veh_min(self) -> float:
        """Alias for delta_wait."""
        return self.delta_wait

    @property
    def delta_avg_queue_veh(self) -> float:
        """Alias for delta_avg_queue."""
        return self.delta_avg_queue

    @property
    def delta_throughput_veh(self) -> float:
        """Alias for delta_throughput."""
        return self.delta_throughput

    def to_dict(self) -> dict[str, Any]:
        """Convert PlanComparison to a JSON-serializable dictionary."""
        return {
            "current_result": self.current_result.to_dict(),
            "proposed_result": self.proposed_result.to_dict(),
            "delta_wait": self.delta_wait,
            "delta_avg_queue": self.delta_avg_queue,
            "delta_throughput": self.delta_throughput,
            "verdict": self.verdict,
        }


class WhatIfSimulator:
    """Pure, deterministic discrete-time macroscopic point-queue traffic simulator.

    Simulates arrival, queuing, and departure dynamics across an intersection under
    candidate signal timing plans for objective comparative ranking.
    """

    def simulate(
        self,
        initial: list[ApproachState],
        plan: SignalPlan,
        config: Optional[SimulationConfig] = None,
    ) -> SimulationResult:
        """Run deterministic point-queue simulation over the configured horizon.

        Dynamics Formulation:
        - For each time-step `dt`, right-of-way is assigned cyclically through phases
          in the plan's insertion order.
        - Each phase runs for `green_s` (service active at saturation flow), followed by
          `yellow_s + all_red_s` clearance lost time (service rate = 0).
        - Approach arrivals accumulate uniformly: `arrivals = arrival_rate * (dt / 60)`.
        - Approach departures are determined by right-of-way:
            `departures = min(queue + arrivals, saturation_flow * (dt / 60))` if green, else 0.
        - Backlogs progress honestly without artificial clamping.

        Args:
            initial: List of ApproachState specifications for all intersection approaches.
            plan: SignalPlan defining phase green splits, clearance times, and approach mapping.
            config: Operational SimulationConfig (defaults to 15 min horizon, 5s dt).

        Returns:
            SimulationResult containing aggregate delay, queues, throughput, and diagnostics.

        Raises:
            ValueError: If duplicate approach IDs or invalid non-positive inputs are detected.
        """
        if config is None:
            config = SimulationConfig()

        digest = compute_plan_digest(plan)
        now = datetime.now(timezone.utc)

        # Edge case: Empty approaches list
        if not initial:
            return SimulationResult(
                total_wait_veh_min=0.0,
                avg_queue_veh=0.0,
                max_queue_veh=0.0,
                throughput_veh=0.0,
                residual_queue_veh=0.0,
                per_approach={},
                plan_digest=digest,
                horizon_minutes=config.horizon_minutes,
                computed_at=now,
                notes=["empty approaches: no approaches provided for simulation"],
            )

        # Check for duplicate approach identifiers
        seen_ids: set[str] = set()
        for app in initial:
            if app.approach_id in seen_ids:
                raise ValueError(
                    f"Duplicate approach_id detected in initial states: '{app.approach_id}'"
                )
            seen_ids.add(app.approach_id)

        # Build cycle timing structure
        # Phases cycle sequentially in defined plan order
        phases_list = list(plan.phases.items())
        lost_time_per_phase = float(plan.yellow_s + plan.all_red_s)
        cycle_s = float(plan.cycle_length_s)

        if cycle_s <= 0:
            raise ValueError(f"Total cycle length must be positive, got {cycle_s}")

        # Precompute phase intervals: [(start_s, green_end_s, phase_end_s, set_of_green_approaches)]
        phase_intervals: list[tuple[float, float, float, set[str]]] = []
        cur_offset = 0.0
        for p_name, g_s in phases_list:
            g_val = float(g_s)
            p_end = cur_offset + g_val + lost_time_per_phase
            apps_in_phase = set(plan.phase_to_approaches.get(p_name, []))
            phase_intervals.append((cur_offset, cur_offset + g_val, p_end, apps_in_phase))
            cur_offset = p_end

        # Check for oversaturated approaches (arrival rate exceeds effective capacity)
        notes: list[str] = []
        for app in initial:
            # Calculate total green duration serving this approach per cycle
            allocated_green_s = sum(
                float(g_s)
                for p_name, g_s in phases_list
                if app.approach_id in plan.phase_to_approaches.get(p_name, [])
            )
            sat_rate = float(
                app.saturation_flow_veh_per_min
                if app.saturation_flow_veh_per_min is not None
                else 30.0 * app.lane_count
            )
            effective_capacity_veh_per_min = (
                sat_rate * (allocated_green_s / cycle_s) if cycle_s > 0 else 0.0
            )

            if app.arrival_rate_veh_per_min > effective_capacity_veh_per_min:
                notes.append(
                    f"oversaturated: approach '{app.approach_id}' arrival rate "
                    f"({app.arrival_rate_veh_per_min:.2f} veh/min) exceeds capacity "
                    f"({effective_capacity_veh_per_min:.2f} veh/min)"
                )
            elif app.arrival_rate_veh_per_min > sat_rate:
                notes.append(
                    f"oversaturated: approach '{app.approach_id}' arrival rate "
                    f"({app.arrival_rate_veh_per_min:.2f} veh/min) exceeds raw saturation flow "
                    f"({sat_rate:.2f} veh/min)"
                )

        # Simulation stepping parameters
        dt = float(config.dt_seconds)
        dt_min = dt / 60.0
        horizon_s = float(config.horizon_minutes) * 60.0
        n_steps = max(1, int(round(horizon_s / dt)))

        # Initialize approach tracking
        current_queues: dict[str, float] = {
            app.approach_id: float(app.queue_veh) for app in initial
        }
        max_queues: dict[str, float] = {
            app.approach_id: float(app.queue_veh) for app in initial
        }
        throughputs: dict[str, float] = {app.approach_id: 0.0 for app in initial}
        cumulative_waits: dict[str, float] = {app.approach_id: 0.0 for app in initial}

        peak_junction_queue = sum(current_queues.values())

        # Discrete-time simulation loop
        for step in range(n_steps):
            t_start = step * dt
            t_cycle = t_start % cycle_s

            # Determine which approaches have right-of-way (green) at this step
            green_approaches: set[str] = set()
            for start_s, green_end_s, phase_end_s, app_set in phase_intervals:
                if start_s <= t_cycle < phase_end_s:
                    if t_cycle < green_end_s:
                        green_approaches = app_set
                    # During clearance lost time [green_end_s, phase_end_s), no approaches have green
                    break

            step_junction_queue = 0.0

            # Update dynamics per approach
            for app in initial:
                aid = app.approach_id
                arr = float(app.arrival_rate_veh_per_min) * dt_min
                available = current_queues[aid] + arr

                sat_flow_dt = (
                    float(
                        app.saturation_flow_veh_per_min
                        if app.saturation_flow_veh_per_min is not None
                        else 30.0 * app.lane_count
                    )
                    * dt_min
                )

                if aid in green_approaches:
                    dep = min(available, sat_flow_dt)
                else:
                    dep = 0.0

                new_queue = available - dep
                current_queues[aid] = new_queue
                throughputs[aid] += dep

                if new_queue > max_queues[aid]:
                    max_queues[aid] = new_queue

                cumulative_waits[aid] += new_queue * dt_min
                step_junction_queue += new_queue

            if step_junction_queue > peak_junction_queue:
                peak_junction_queue = step_junction_queue

        # Aggregate metrics across all approaches
        total_wait_veh_min = sum(cumulative_waits.values())
        avg_queue_veh = total_wait_veh_min / float(config.horizon_minutes)
        total_throughput_veh = sum(throughputs.values())
        total_residual_queue_veh = sum(current_queues.values())

        per_approach_results: dict[str, ApproachSimulationResult] = {}
        for app in initial:
            aid = app.approach_id
            app_wait = cumulative_waits[aid]
            per_approach_results[aid] = ApproachSimulationResult(
                approach_id=aid,
                total_wait_veh_min=round(app_wait, 4),
                avg_queue_veh=round(app_wait / float(config.horizon_minutes), 4),
                max_queue_veh=round(max_queues[aid], 4),
                throughput_veh=round(throughputs[aid], 4),
                residual_queue_veh=round(current_queues[aid], 4),
            )

        return SimulationResult(
            total_wait_veh_min=round(total_wait_veh_min, 4),
            avg_queue_veh=round(avg_queue_veh, 4),
            max_queue_veh=round(peak_junction_queue, 4),
            throughput_veh=round(total_throughput_veh, 4),
            residual_queue_veh=round(total_residual_queue_veh, 4),
            per_approach=per_approach_results,
            plan_digest=digest,
            horizon_minutes=float(config.horizon_minutes),
            computed_at=now,
            notes=notes,
        )

    def compare(
        self,
        initial: list[ApproachState],
        current_plan: SignalPlan,
        proposed_plan: SignalPlan,
        config: Optional[SimulationConfig] = None,
    ) -> PlanComparison:
        """Compare two candidate signal plans under identical initial traffic conditions.

        Runs deterministic point-queue simulation on both plans, computes raw physical
        deltas (proposed - current), and selects a deterministic verdict.

        VERDICT RULE:
        - 'proposed_better' if delta_wait < -1e-9
        - 'current_better' if delta_wait > 1e-9
        - 'equivalent' otherwise

        CRITICAL REPORTING INVARIANT:
        The verdict and raw deltas are the ONLY comparative claims emitted.
        Percentage-improvement statements are strictly prohibited.

        Args:
            initial: ApproachState specifications for all intersection approaches.
            current_plan: Baseline / current SignalPlan.
            proposed_plan: Candidate / proposed SignalPlan.
            config: Operational SimulationConfig (defaults to 15 min horizon, 5s dt).

        Returns:
            PlanComparison object containing both SimulationResults, physical deltas, and verdict.
        """
        if config is None:
            config = SimulationConfig()

        current_res = self.simulate(initial, current_plan, config)
        proposed_res = self.simulate(initial, proposed_plan, config)

        delta_wait = proposed_res.total_wait_veh_min - current_res.total_wait_veh_min
        delta_avg_queue = proposed_res.avg_queue_veh - current_res.avg_queue_veh
        delta_throughput = proposed_res.throughput_veh - current_res.throughput_veh

        if delta_wait < -1e-9:
            verdict = "proposed_better"
        elif delta_wait > 1e-9:
            verdict = "current_better"
        else:
            verdict = "equivalent"

        return PlanComparison(
            current_result=current_res,
            proposed_result=proposed_res,
            delta_wait=round(delta_wait, 4),
            delta_avg_queue=round(delta_avg_queue, 4),
            delta_throughput=round(delta_throughput, 4),
            verdict=verdict,
        )
