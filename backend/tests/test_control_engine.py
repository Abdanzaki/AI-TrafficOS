"""Pure unit tests for traffic control engine components (Phase 6).

Covers:
- SignalOptimizer (Webster-inspired queue-proportional split allocation, clamping, zero-demand, emergency bump, determinism)
- WhatIfSimulator (macroscopic point-queue simulation, honest residual accounting, plan comparison verdicts, determinism, input validation)
- DecisionEngine / evaluate_control_rules (deterministic rule evaluation hierarchy, recommendations invariant)
"""

import math
import pytest

from app.services.control.decisions import (
    DecisionEngine,
    QUEUE_GROWTH_REROUTE_THRESHOLD,
    QUEUE_LENGTH_EXTEND_GREEN_THRESHOLD,
    QUEUE_LENGTH_REDUCE_GREEN_THRESHOLD,
    QUEUE_LENGTH_REROUTE_THRESHOLD,
    evaluate_control_rules,
)
from app.services.control.optimization import (
    CycleConfig,
    PhaseDemand,
    SignalOptimizer,
)
from app.services.control.schemas import (
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


# ==============================================================================
# 1. SignalOptimizer Tests
# ==============================================================================


def test_optimizer_proportional_allocation_sums_correctly():
    """Verify discretionary green is allocated proportionally to demand and total cycle sums correctly."""
    demands = [
        PhaseDemand(
            phase_id=1,
            phase_name="NB_THRU",
            queue_length=10.0,
            density=0.3,
            flow_veh_per_min=15.0,
            lane_count=1,
        ),
        PhaseDemand(
            phase_id=2,
            phase_name="SB_THRU",
            queue_length=30.0,
            density=0.6,
            flow_veh_per_min=35.0,
            lane_count=1,
        ),
    ]
    cfg = CycleConfig(min_green_s=7.0, max_green_s=60.0, yellow_s=3.0, all_red_s=2.0)
    result = SignalOptimizer.optimize(demands, cycle_config=cfg)

    # 1. Higher demand phase receives greater green split
    assert result.recommended_green_s[2] > result.recommended_green_s[1]

    # 2. Cycle sum: sum of greens + sum of clearances == total_cycle_s
    clearance_per_phase = cfg.yellow_s + cfg.all_red_s
    expected_cycle = sum(result.recommended_green_s.values()) + (len(demands) * clearance_per_phase)
    assert math.isclose(result.total_cycle_s, expected_cycle, abs_tol=0.01)

    # 3. Echoed inputs match calculated demand scores
    assert 1 in result.inputs_echo
    assert 2 in result.inputs_echo
    assert result.inputs_echo[2] > result.inputs_echo[1]


def test_optimizer_min_max_clamping():
    """Verify that green splits never violate [min_green_s, max_green_s] bounds."""
    # Phase with extreme demand should be capped at max_green_s (50.0)
    # Phase with minimal demand should not drop below min_green_s (10.0)
    demands = [
        PhaseDemand(
            phase_id=10,
            phase_name="MAJOR_APPROACH",
            queue_length=300.0,
            density=0.99,
            flow_veh_per_min=100.0,
            lane_count=3,
        ),
        PhaseDemand(
            phase_id=20,
            phase_name="MINOR_SIDE_STREET",
            queue_length=0.1,
            density=0.01,
            flow_veh_per_min=0.5,
            lane_count=1,
        ),
    ]
    cfg = CycleConfig(min_green_s=10.0, max_green_s=50.0, yellow_s=3.0, all_red_s=2.0)
    result = SignalOptimizer.optimize(demands, cycle_config=cfg)

    assert result.recommended_green_s[10] <= cfg.max_green_s
    assert math.isclose(result.recommended_green_s[10], cfg.max_green_s, abs_tol=0.01)
    assert result.recommended_green_s[20] >= cfg.min_green_s
    assert math.isclose(result.recommended_green_s[20], cfg.min_green_s, abs_tol=0.5)


def test_optimizer_zero_demand_all_min_green():
    """Verify that when total approach demand is zero, all phases receive statutory min_green."""
    demands = [
        PhaseDemand(
            phase_id=101,
            phase_name="APPROACH_1",
            queue_length=0.0,
            density=0.0,
            flow_veh_per_min=0.0,
        ),
        PhaseDemand(
            phase_id=102,
            phase_name="APPROACH_2",
            queue_length=0.0,
            density=0.0,
            flow_veh_per_min=0.0,
        ),
    ]
    cfg = CycleConfig(min_green_s=8.0, max_green_s=55.0, yellow_s=3.0, all_red_s=2.0)
    result = SignalOptimizer.optimize(demands, cycle_config=cfg)

    assert result.note == "no demand"
    assert result.recommended_green_s[101] == 8.0
    assert result.recommended_green_s[102] == 8.0
    # Total cycle = 2 * (8.0 + 3.0 + 2.0) = 26.0s
    assert result.total_cycle_s == 26.0


def test_optimizer_emergency_bump_increases_share():
    """Verify that emergency route phase receives a 1.5x score boost and higher green allocation."""
    # Two phases with identical physical demand
    demand_normal = PhaseDemand(
        phase_id=1,
        phase_name="CIVILIAN_PHASE",
        queue_length=15.0,
        density=0.3,
        flow_veh_per_min=20.0,
        lane_count=1,
        is_emergency_route=False,
    )
    demand_emergency = PhaseDemand(
        phase_id=2,
        phase_name="EMERGENCY_CORRIDOR_PHASE",
        queue_length=15.0,
        density=0.3,
        flow_veh_per_min=20.0,
        lane_count=1,
        is_emergency_route=True,
    )

    optimizer = SignalOptimizer()
    score_normal = optimizer.compute_phase_demand_score(demand_normal)
    score_emergency = optimizer.compute_phase_demand_score(demand_emergency)

    assert math.isclose(score_emergency, score_normal * 1.5, rel_tol=1e-3)

    result = optimizer.optimize([demand_normal, demand_emergency])
    assert result.recommended_green_s[2] > result.recommended_green_s[1]


def test_optimizer_determinism():
    """Verify optimizer is completely deterministic given identical inputs."""
    demands = [
        PhaseDemand(phase_id=1, phase_name="P1", queue_length=12.0, density=0.25, flow_veh_per_min=18.0),
        PhaseDemand(phase_id=2, phase_name="P2", queue_length=22.0, density=0.45, flow_veh_per_min=28.0),
        PhaseDemand(phase_id=3, phase_name="P3", queue_length=8.0, density=0.15, flow_veh_per_min=10.0),
    ]
    cfg = CycleConfig(min_green_s=7.0, max_green_s=60.0)

    res1 = SignalOptimizer.optimize(demands, cycle_config=cfg)
    res2 = SignalOptimizer.optimize(demands, cycle_config=cfg)

    assert res1.recommended_green_s == res2.recommended_green_s
    assert res1.total_cycle_s == res2.total_cycle_s
    assert res1.inputs_echo == res2.inputs_echo


# ==============================================================================
# 2. WhatIfSimulator Tests
# ==============================================================================


def test_simulator_simulate_returns_finite_non_negative_numbers():
    """Verify simulation results contain finite, non-negative delay and throughput values."""
    approaches = [
        ApproachState(
            approach_id="NB",
            queue_veh=15.0,
            arrival_rate_veh_per_min=10.0,
            saturation_flow_veh_per_min=30.0,
            lane_count=1,
        ),
        ApproachState(
            approach_id="SB",
            queue_veh=8.0,
            arrival_rate_veh_per_min=8.0,
            saturation_flow_veh_per_min=30.0,
            lane_count=1,
        ),
    ]
    plan = SignalPlan(
        phases={"phase_nb": 30.0, "phase_sb": 25.0},
        phase_to_approaches={"phase_nb": ["NB"], "phase_sb": ["SB"]},
        yellow_s=3.0,
        all_red_s=2.0,
    )
    sim = WhatIfSimulator()
    res = sim.simulate(approaches, plan, SimulationConfig(horizon_minutes=10.0, dt_seconds=5.0))

    assert res.total_wait_veh_min >= 0.0 and math.isfinite(res.total_wait_veh_min)
    assert res.avg_queue_veh >= 0.0 and math.isfinite(res.avg_queue_veh)
    assert res.max_queue_veh >= 0.0 and math.isfinite(res.max_queue_veh)
    assert res.throughput_veh >= 0.0 and math.isfinite(res.throughput_veh)
    assert res.residual_queue_veh >= 0.0 and math.isfinite(res.residual_queue_veh)

    for aid in ["NB", "SB"]:
        app_res = res.per_approach[aid]
        assert app_res.total_wait_veh_min >= 0.0
        assert app_res.throughput_veh >= 0.0
        assert app_res.residual_queue_veh >= 0.0


def test_simulator_compare_verdicts_proposed_better_and_equivalent():
    """Verify compare returns 'proposed_better' when favoring the congested approach and 'equivalent' on identical plans."""
    app_heavy = ApproachState(
        approach_id="HEAVY_APPROACH",
        queue_veh=35.0,
        arrival_rate_veh_per_min=24.0,
        saturation_flow_veh_per_min=30.0,
        lane_count=1,
    )
    app_light = ApproachState(
        approach_id="LIGHT_APPROACH",
        queue_veh=2.0,
        arrival_rate_veh_per_min=3.0,
        saturation_flow_veh_per_min=30.0,
        lane_count=1,
    )
    approaches = [app_heavy, app_light]

    # Baseline plan starves the heavy approach (only 12s green) and over-serves the light approach (45s green)
    baseline_plan = SignalPlan(
        phases={"p_heavy": 12.0, "p_light": 45.0},
        phase_to_approaches={"p_heavy": ["HEAVY_APPROACH"], "p_light": ["LIGHT_APPROACH"]},
        yellow_s=3.0,
        all_red_s=2.0,
    )

    # Proposed plan allocates generous green to the heavy approach (45s green) and right-sizes the light approach (15s green)
    proposed_plan = SignalPlan(
        phases={"p_heavy": 45.0, "p_light": 15.0},
        phase_to_approaches={"p_heavy": ["HEAVY_APPROACH"], "p_light": ["LIGHT_APPROACH"]},
        yellow_s=3.0,
        all_red_s=2.0,
    )

    sim = WhatIfSimulator()
    comparison = sim.compare(approaches, baseline_plan, proposed_plan)

    # Verdict must be proposed_better with negative delay delta
    assert comparison.verdict == "proposed_better"
    assert comparison.delta_wait < 0.0
    assert comparison.delta_avg_queue < 0.0
    assert comparison.proposed_result.total_wait_veh_min < comparison.current_result.total_wait_veh_min

    # Comparing identical baseline plan with itself must yield 'equivalent'
    equiv_comparison = sim.compare(approaches, baseline_plan, baseline_plan)
    assert equiv_comparison.verdict == "equivalent"
    assert math.isclose(equiv_comparison.delta_wait, 0.0, abs_tol=1e-6)
    assert math.isclose(equiv_comparison.delta_avg_queue, 0.0, abs_tol=1e-6)


def test_simulator_oversaturated_approach_reports_residual_honestly():
    """Verify oversaturated approach backlog grows honestly and is flagged in diagnostic notes."""
    # Arrival rate 28 veh/min with effective capacity around 10 veh/min
    app_congested = ApproachState(
        approach_id="BOTTLE_NECK",
        queue_veh=20.0,
        arrival_rate_veh_per_min=28.0,
        saturation_flow_veh_per_min=30.0,
        lane_count=1,
    )
    plan = SignalPlan(
        phases={"phase_1": 15.0},
        phase_to_approaches={"phase_1": ["BOTTLE_NECK"]},
        yellow_s=3.0,
        all_red_s=2.0,
    )

    sim = WhatIfSimulator()
    res = sim.simulate([app_congested], plan, SimulationConfig(horizon_minutes=15.0, dt_seconds=5.0))

    # Queue must expand beyond initial value (residual > 20.0)
    assert res.residual_queue_veh > app_congested.queue_veh
    # Diagnostic notes must explicitly report oversaturation
    assert any("oversaturated" in n.lower() for n in res.notes)


def test_simulator_invalid_inputs_raise_value_error():
    """Verify simulator validates input constraints and rejects invalid configurations."""
    # Negative queue
    with pytest.raises(ValueError, match="queue_veh cannot be negative"):
        ApproachState(approach_id="A1", queue_veh=-5.0, arrival_rate_veh_per_min=10.0)

    # Negative arrival rate
    with pytest.raises(ValueError, match="arrival_rate_veh_per_min cannot be negative"):
        ApproachState(approach_id="A1", queue_veh=0.0, arrival_rate_veh_per_min=-1.0)

    # Empty approach ID
    with pytest.raises(ValueError, match="approach_id cannot be empty"):
        ApproachState(approach_id="", queue_veh=0.0, arrival_rate_veh_per_min=5.0)

    # Negative clearance intervals
    with pytest.raises(ValueError, match="yellow_s cannot be negative"):
        SignalPlan(phases={"p1": 20.0}, phase_to_approaches={}, yellow_s=-1.0)

    # Empty phases in signal plan
    with pytest.raises(ValueError, match="phases cannot be empty"):
        SignalPlan(phases={}, phase_to_approaches={})

    # Non-positive phase green duration
    with pytest.raises(ValueError, match="must be positive"):
        SignalPlan(phases={"p1": 0.0}, phase_to_approaches={})

    # Duplicate approach IDs passed to simulator
    app1 = ApproachState(approach_id="DUP", queue_veh=5.0, arrival_rate_veh_per_min=5.0)
    app2 = ApproachState(approach_id="DUP", queue_veh=2.0, arrival_rate_veh_per_min=3.0)
    valid_plan = SignalPlan(phases={"p1": 20.0}, phase_to_approaches={"p1": ["DUP"]})

    with pytest.raises(ValueError, match="Duplicate approach_id detected"):
        WhatIfSimulator().simulate([app1, app2], valid_plan)


def test_simulator_determinism():
    """Verify simulator runs deterministically across multiple identical evaluations."""
    approaches = [
        ApproachState(approach_id="E1", queue_veh=10.0, arrival_rate_veh_per_min=12.0),
        ApproachState(approach_id="W1", queue_veh=14.0, arrival_rate_veh_per_min=15.0),
    ]
    plan = SignalPlan(
        phases={"phase_ew": 35.0},
        phase_to_approaches={"phase_ew": ["E1", "W1"]},
        yellow_s=3.0,
        all_red_s=2.0,
    )
    sim = WhatIfSimulator()
    cfg = SimulationConfig(horizon_minutes=12.0, dt_seconds=4.0)

    r1 = sim.simulate(approaches, plan, cfg)
    r2 = sim.simulate(approaches, plan, cfg)

    assert r1.total_wait_veh_min == r2.total_wait_veh_min
    assert r1.avg_queue_veh == r2.avg_queue_veh
    assert r1.throughput_veh == r2.throughput_veh
    assert r1.residual_queue_veh == r2.residual_queue_veh
    assert r1.plan_digest == r2.plan_digest


# ==============================================================================
# 3. DecisionEngine & Rule Evaluation Tests
# ==============================================================================


def test_decision_rules_active_emergency():
    """Verify active emergency vehicle transit immediately triggers PRIORITIZE_EMERGENCY."""
    state = TrafficState(
        intersection_id=10,
        vehicle_count=20,
        density=0.3,
        queue_length=10.0,
        occupancy=0.35,
        active_emergency=True,
        telemetry_age_s=15.0,
    )
    dec = evaluate_control_rules(state, predicted=None)

    assert dec.action == DecisionAction.PRIORITIZE_EMERGENCY
    assert dec.is_recommendation is True
    assert len(dec.reason) > 0
    assert len(dec.expected_impact) > 0
    assert dec.confidence == 0.9


def test_decision_rules_reroute_traffic_on_saturation():
    """Verify queue >= 25 and predicted queue growth > 2.0 triggers REROUTE_TRAFFIC."""
    state = TrafficState(
        intersection_id=20,
        vehicle_count=60,
        density=0.7,
        queue_length=QUEUE_LENGTH_REROUTE_THRESHOLD + 2.0,  # 27.0 >= 25.0
        occupancy=0.75,
        active_emergency=False,
        telemetry_age_s=20.0,
    )
    predicted = PredictedState(
        congestion=85.0,
        volume=90.0,
        queue_growth=QUEUE_GROWTH_REROUTE_THRESHOLD + 0.5,  # 2.5 > 2.0
        horizon_minutes=30,
        model_version="xgb_v2",
        confidence=0.88,
    )
    dec = evaluate_control_rules(state, predicted)

    assert dec.action == DecisionAction.REROUTE_TRAFFIC
    assert dec.is_recommendation is True
    assert len(dec.reason) > 0
    assert "reroute" in dec.reason.lower() or "detour" in dec.reason.lower()
    assert len(dec.expected_impact) > 0
    assert dec.model_version == "xgb_v2"
    assert dec.confidence == 0.88


def test_decision_rules_extend_green_on_queue():
    """Verify queue >= 15 triggers EXTEND_GREEN split adjustment."""
    state = TrafficState(
        intersection_id=30,
        vehicle_count=35,
        density=0.45,
        queue_length=QUEUE_LENGTH_EXTEND_GREEN_THRESHOLD + 1.0,  # 16.0 >= 15.0
        occupancy=0.4,
        active_emergency=False,
        telemetry_age_s=10.0,
    )
    dec = evaluate_control_rules(state, predicted=None)

    assert dec.action == DecisionAction.EXTEND_GREEN
    assert dec.is_recommendation is True
    assert len(dec.reason) > 0
    assert len(dec.expected_impact) > 0
    assert dec.confidence == 0.65


def test_decision_rules_reduce_green_on_low_demand():
    """Verify low density (<= 0.15) and short queue (<= 3.0) triggers REDUCE_GREEN."""
    state = TrafficState(
        intersection_id=40,
        vehicle_count=4,
        density=0.10,  # <= 0.15
        queue_length=QUEUE_LENGTH_REDUCE_GREEN_THRESHOLD - 1.0,  # 2.0 <= 3.0
        occupancy=0.08,
        active_emergency=False,
        telemetry_age_s=12.0,
    )
    dec = evaluate_control_rules(state, predicted=None)

    assert dec.action == DecisionAction.REDUCE_GREEN
    assert dec.is_recommendation is True
    assert len(dec.reason) > 0
    assert "low demand" in dec.reason.lower()
    assert len(dec.expected_impact) > 0
    assert dec.confidence == 0.65


def test_decision_rules_nominal_conditions_yield_no_action():
    """Verify nominal traffic conditions result in advisory NO_ACTION."""
    state = TrafficState(
        intersection_id=50,
        vehicle_count=18,
        density=0.30,  # between 0.15 and heavy
        queue_length=8.0,  # between 3.0 and 15.0
        occupancy=0.28,
        active_emergency=False,
        telemetry_age_s=15.0,
    )
    dec = evaluate_control_rules(state, predicted=None)

    assert dec.action == DecisionAction.NO_ACTION
    assert dec.is_recommendation is True
    assert "normal" in dec.reason.lower() or "within normal bounds" in dec.reason.lower()
    assert dec.confidence is None


def test_decision_engine_propose_invariants():
    """Verify DecisionEngine enforces recommendation invariant and handles missing/stale telemetry."""
    engine = DecisionEngine(max_telemetry_age_s=300.0)

    # 1. Missing state -> NO_ACTION fallback with is_recommendation True
    dec_none = engine.propose(None)
    assert dec_none.action == DecisionAction.NO_ACTION
    assert dec_none.is_recommendation is True
    assert len(dec_none.reason) > 0

    # 2. Stale state (> 300s) -> defensive NO_ACTION fallback with is_recommendation True
    state_stale = TrafficState(
        intersection_id=60,
        vehicle_count=20,
        density=0.3,
        queue_length=8.0,
        occupancy=0.3,
        telemetry_age_s=350.0,
    )
    dec_stale = engine.propose(state_stale)
    assert dec_stale.action == DecisionAction.NO_ACTION
    assert dec_stale.is_recommendation is True
    assert "stale" in dec_stale.reason.lower()

    # 3. Every non-NO_ACTION decision from engine has non-empty reason and expected_impact
    state_busy = TrafficState(
        intersection_id=60,
        vehicle_count=40,
        density=0.5,
        queue_length=18.0,
        occupancy=0.5,
        telemetry_age_s=25.0,
    )
    dec_busy = engine.propose(state_busy)
    assert dec_busy.action != DecisionAction.NO_ACTION
    assert len(dec_busy.reason.strip()) > 0
    assert len(dec_busy.expected_impact.strip()) > 0
    assert dec_busy.is_recommendation is True
