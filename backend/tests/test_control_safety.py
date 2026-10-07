"""Pure unit tests for traffic control safety validation service (Phase 6).

Covers SafetyValidator and ValidatedPlan from app.services.control.safety:
- Timing bounds validation (min_green, max_green)
- Cyclic phase transition enforcement and inactive phase lockout
- Conflict detection heuristic (conflicting greens naming pair, compatible opposing throughs, dual lefts)
- Telemetry freshness enforcement (ensure_no_action_on_stale)
- Holistic plan validation (validate_plan) returning ValidatedPlan
"""

from datetime import datetime, timezone
import pytest

from app.models.signal import SignalPhase
from app.services.control.exceptions import StaleTelemetryError, UnsafeStateError
from app.services.control.optimization import CycleConfig
from app.services.control.safety import SafetyValidator, ValidatedPlan


# ==============================================================================
# 1. Timing Bounds Validation Tests
# ==============================================================================


def test_validate_timing_green_below_min_raises():
    """Verify that proposed green shorter than min_green_s raises UnsafeStateError."""
    config = CycleConfig(min_green_s=7.0, max_green_s=60.0)
    with pytest.raises(UnsafeStateError, match="violates safety bounds"):
        SafetyValidator.validate_timing(
            signal_id=1,
            phase_id=101,
            proposed_green_s=5.0,  # Below min 7.0s
            config=config,
        )


def test_validate_timing_green_above_max_raises():
    """Verify that proposed green longer than max_green_s raises UnsafeStateError."""
    config = CycleConfig(min_green_s=7.0, max_green_s=60.0)
    with pytest.raises(UnsafeStateError, match="violates safety bounds"):
        SafetyValidator.validate_timing(
            signal_id=1,
            phase_id=101,
            proposed_green_s=65.0,  # Above max 60.0s
            config=config,
        )


def test_validate_timing_green_within_bounds_passes():
    """Verify that proposed green within [min_green_s, max_green_s] passes without error."""
    config = CycleConfig(min_green_s=7.0, max_green_s=60.0)
    # Exact bounds and intermediate values should all pass
    SafetyValidator.validate_timing(signal_id=1, phase_id=101, proposed_green_s=7.0, config=config)
    SafetyValidator.validate_timing(signal_id=1, phase_id=101, proposed_green_s=30.0, config=config)
    SafetyValidator.validate_timing(signal_id=1, phase_id=101, proposed_green_s=60.0, config=config)


# ==============================================================================
# 2. Phase Transition & Inactive Phase Lockout Tests
# ==============================================================================


def test_validate_phase_transition_skipping_order_raises():
    """Verify that skipping phase_order in sequence raises UnsafeStateError naming invalid transition."""
    p1 = SignalPhase(id=1, signal_id=10, name="NB Thru", phase_order=1, is_active=True)
    p2 = SignalPhase(id=2, signal_id=10, name="SB Thru", phase_order=2, is_active=True)
    p3 = SignalPhase(id=3, signal_id=10, name="EB Thru", phase_order=3, is_active=True)
    phases = [p1, p2, p3]

    # Skipping phase 2: attempting 1 -> 3
    with pytest.raises(UnsafeStateError, match="invalid phase transition"):
        SafetyValidator.validate_phase_transition(phases=phases, from_phase_id=1, to_phase_id=3)

    # Reverse transition: attempting 2 -> 1
    with pytest.raises(UnsafeStateError, match="invalid phase transition"):
        SafetyValidator.validate_phase_transition(phases=phases, from_phase_id=2, to_phase_id=1)


def test_validate_phase_transition_to_inactive_phase_raises():
    """Verify that transitioning to an inactive phase raises UnsafeStateError."""
    p1 = SignalPhase(id=1, signal_id=10, name="NB Thru", phase_order=1, is_active=True)
    p2 = SignalPhase(id=2, signal_id=10, name="EB Thru", phase_order=2, is_active=False)
    phases = [p1, p2]

    with pytest.raises(UnsafeStateError, match="cannot transition to inactive phase"):
        SafetyValidator.validate_phase_transition(phases=phases, from_phase_id=1, to_phase_id=2)


def test_validate_phase_transition_from_inactive_phase_raises():
    """Verify that transitioning from an inactive phase raises UnsafeStateError."""
    p1 = SignalPhase(id=1, signal_id=10, name="NB Thru", phase_order=1, is_active=False)
    p2 = SignalPhase(id=2, signal_id=10, name="EB Thru", phase_order=2, is_active=True)
    phases = [p1, p2]

    with pytest.raises(UnsafeStateError, match="origin phase 1 .* is inactive"):
        SafetyValidator.validate_phase_transition(phases=phases, from_phase_id=1, to_phase_id=2)


def test_validate_phase_transition_nonexistent_phase_raises():
    """Verify that transitions referencing nonexistent phases raise UnsafeStateError."""
    p1 = SignalPhase(id=1, signal_id=10, name="NB Thru", phase_order=1, is_active=True)
    phases = [p1]

    with pytest.raises(UnsafeStateError, match="destination phase 999 does not exist"):
        SafetyValidator.validate_phase_transition(phases=phases, from_phase_id=1, to_phase_id=999)

    with pytest.raises(UnsafeStateError, match="origin phase 888 does not exist"):
        SafetyValidator.validate_phase_transition(phases=phases, from_phase_id=888, to_phase_id=1)


def test_validate_phase_transition_valid_progression_passes():
    """Verify that proper sequential progression, cyclic wrap-around, and green extensions pass."""
    p1 = SignalPhase(id=1, signal_id=10, name="NB Thru", phase_order=1, is_active=True)
    p2 = SignalPhase(id=2, signal_id=10, name="SB Thru", phase_order=2, is_active=True)
    p3 = SignalPhase(id=3, signal_id=10, name="EB Thru", phase_order=3, is_active=True)
    phases = [p1, p2, p3]

    # Normal step progression
    SafetyValidator.validate_phase_transition(phases=phases, from_phase_id=1, to_phase_id=2)
    SafetyValidator.validate_phase_transition(phases=phases, from_phase_id=2, to_phase_id=3)

    # Cyclic wrap-around (last -> first)
    SafetyValidator.validate_phase_transition(phases=phases, from_phase_id=3, to_phase_id=1)

    # Same phase green extension
    SafetyValidator.validate_phase_transition(phases=phases, from_phase_id=1, to_phase_id=1)


# ==============================================================================
# 3. Conflict Detection Tests
# ==============================================================================


def test_check_conflicts_conflicting_greens_raise_naming_pair():
    """Verify that conflicting concurrent green movements raise UnsafeStateError naming both phases."""
    p_nb = SignalPhase(id=1, signal_id=10, name="Northbound Through", phase_order=1, is_active=True)
    p_eb = SignalPhase(id=2, signal_id=10, name="Eastbound Through", phase_order=2, is_active=True)
    phases = [p_nb, p_eb]

    with pytest.raises(UnsafeStateError) as exc_info:
        SafetyValidator.check_conflicts(phases=phases, green_phase_ids=[1, 2])

    err_msg = str(exc_info.value)
    assert "Phase conflict detected" in err_msg
    # Ensure both phases are explicitly named in the error message
    assert "phase 1" in err_msg and "Northbound Through" in err_msg
    assert "phase 2" in err_msg and "Eastbound Through" in err_msg


def test_check_conflicts_through_vs_opposing_left_raises_naming_pair():
    """Verify that NB Through vs SB Left raises UnsafeStateError naming both conflicting phases."""
    p_nb = SignalPhase(id=10, signal_id=10, name="NB Through", phase_order=1, is_active=True)
    p_sbl = SignalPhase(id=20, signal_id=10, name="SB Left", phase_order=2, is_active=True)
    phases = [p_nb, p_sbl]

    with pytest.raises(UnsafeStateError) as exc_info:
        SafetyValidator.check_conflicts(phases=phases, green_phase_ids=[10, 20])

    err_msg = str(exc_info.value)
    assert "Phase conflict detected" in err_msg
    assert "phase 10" in err_msg and "NB Through" in err_msg
    assert "phase 20" in err_msg and "SB Left" in err_msg


def test_check_conflicts_compatible_opposing_through_movements_pass():
    """Verify that opposing straight/through movements on North-South and East-West axes pass."""
    # North-South opposing through movements
    p_nb = SignalPhase(id=1, signal_id=10, name="Northbound Through", phase_order=1, is_active=True)
    p_sb = SignalPhase(id=2, signal_id=10, name="Southbound Through", phase_order=1, is_active=True)
    SafetyValidator.check_conflicts(phases=[p_nb, p_sb], green_phase_ids=[1, 2])

    # East-West opposing through movements
    p_eb = SignalPhase(id=3, signal_id=10, name="Eastbound Through", phase_order=2, is_active=True)
    p_wb = SignalPhase(id=4, signal_id=10, name="Westbound Through", phase_order=2, is_active=True)
    SafetyValidator.check_conflicts(phases=[p_eb, p_wb], green_phase_ids=[3, 4])


def test_check_conflicts_compatible_dual_left_and_same_approach_pass():
    """Verify that dual protected left turns, same-approach movements, and explicit tags pass."""
    # Dual protected lefts: NB Left + SB Left
    p_nbl = SignalPhase(id=11, signal_id=10, name="NB Left", phase_order=1, is_active=True)
    p_sbl = SignalPhase(id=12, signal_id=10, name="SB Left", phase_order=1, is_active=True)
    SafetyValidator.check_conflicts(phases=[p_nbl, p_sbl], green_phase_ids=[11, 12])

    # Same approach: NB Through + NB Right
    p_nbr = SignalPhase(id=13, signal_id=10, name="NB Right", phase_order=1, is_active=True)
    SafetyValidator.check_conflicts(phases=[p_nbl, p_nbr], green_phase_ids=[11, 13])

    # Explicit compatibility markers
    p_c1 = SignalPhase(id=21, signal_id=10, name="PhaseA compatible_with:group_alpha", phase_order=3, is_active=True)
    p_c2 = SignalPhase(id=22, signal_id=10, name="PhaseB compatible_with:group_alpha", phase_order=3, is_active=True)
    SafetyValidator.check_conflicts(phases=[p_c1, p_c2], green_phase_ids=[21, 22])

    # Single green phase or empty green list
    SafetyValidator.check_conflicts(phases=[p_nbl], green_phase_ids=[11])
    SafetyValidator.check_conflicts(phases=[p_nbl], green_phase_ids=[])


def test_check_conflicts_nonexistent_phase_raises():
    """Verify that checking conflicts with an unconfigured phase raises UnsafeStateError."""
    p1 = SignalPhase(id=1, signal_id=10, name="NB Thru", phase_order=1, is_active=True)
    with pytest.raises(UnsafeStateError, match="does not exist in intersection phases"):
        SafetyValidator.check_conflicts(phases=[p1], green_phase_ids=[1, 999])


# ==============================================================================
# 4. Telemetry Freshness Validation Tests
# ==============================================================================


def test_ensure_no_action_on_stale_telemetry_raises():
    """Verify that telemetry older than max_age_s raises StaleTelemetryError with diagnostic attributes."""
    with pytest.raises(StaleTelemetryError) as exc_info:
        SafetyValidator.ensure_no_action_on_stale(
            telemetry_age_s=360.0,
            max_age_s=300.0,
            intersection_id=42,
        )

    exc = exc_info.value
    assert exc.intersection_id == 42
    assert exc.age_s == 360.0
    assert exc.max_telemetry_age_s == 300.0
    assert "360.0s exceeds threshold 300.0s" in str(exc)


def test_ensure_no_action_on_fresh_telemetry_passes():
    """Verify that telemetry within max_age_s passes without error."""
    # Fresh telemetry
    SafetyValidator.ensure_no_action_on_stale(telemetry_age_s=12.5, max_age_s=300.0, intersection_id=42)
    # Boundary exact value
    SafetyValidator.ensure_no_action_on_stale(telemetry_age_s=300.0, max_age_s=300.0, intersection_id=42)


# ==============================================================================
# 5. Holistic Plan Validation Tests
# ==============================================================================


def test_validate_plan_sane_plan_returns_validated_plan():
    """Verify validate_plan certifies a sane plan and returns a ValidatedPlan with correct cycle math."""
    p1 = SignalPhase(id=1, signal_id=10, intersection_id=5, name="Northbound Through", phase_order=1, is_active=True, state="red")
    p2 = SignalPhase(id=2, signal_id=10, intersection_id=5, name="Eastbound Through", phase_order=2, is_active=True, state="red")
    phases = [p1, p2]

    proposed_greens = {1: 25.0, 2: 35.0}
    config = CycleConfig(min_green_s=10.0, max_green_s=60.0, yellow_s=3.0, all_red_s=2.0)

    validated = SafetyValidator.validate_plan(
        intersection_id=5,
        proposed_greens=proposed_greens,
        phases=phases,
        config=config,
    )

    assert isinstance(validated, ValidatedPlan)
    assert validated.is_valid is True
    assert validated.intersection_id == 5
    assert validated.proposed_greens == {1: 25.0, 2: 35.0}
    # Total cycle = 25.0 + 35.0 + 2 phases * (3.0 + 2.0 clearance) = 70.0s
    assert validated.total_cycle_s == 70.0
    assert isinstance(validated.validated_at, datetime)
    assert validated.validated_at.tzinfo == timezone.utc


def test_validate_plan_empty_inputs_raise():
    """Verify that validating a plan with empty phases or greens raises UnsafeStateError."""
    p1 = SignalPhase(id=1, signal_id=10, intersection_id=5, name="NB Thru", phase_order=1, is_active=True)
    config = CycleConfig()

    with pytest.raises(UnsafeStateError, match="no signal phases configured"):
        SafetyValidator.validate_plan(intersection_id=5, proposed_greens={1: 20.0}, phases=[], config=config)

    with pytest.raises(UnsafeStateError, match="empty proposed green allocations"):
        SafetyValidator.validate_plan(intersection_id=5, proposed_greens={}, phases=[p1], config=config)


def test_validate_plan_references_nonexistent_or_inactive_phase_raises():
    """Verify allocating green to nonexistent or inactive phase raises UnsafeStateError."""
    p1 = SignalPhase(id=1, signal_id=10, intersection_id=5, name="NB Thru", phase_order=1, is_active=True)
    p2 = SignalPhase(id=2, signal_id=10, intersection_id=5, name="EB Thru", phase_order=2, is_active=False)
    config = CycleConfig()

    # Nonexistent phase ID 99
    with pytest.raises(UnsafeStateError, match="references nonexistent phase_id 99"):
        SafetyValidator.validate_plan(intersection_id=5, proposed_greens={99: 20.0}, phases=[p1, p2], config=config)

    # Inactive phase ID 2
    with pytest.raises(UnsafeStateError, match="Cannot allocate green time .* to inactive phase 2"):
        SafetyValidator.validate_plan(intersection_id=5, proposed_greens={1: 20.0, 2: 20.0}, phases=[p1, p2], config=config)


def test_validate_plan_timing_violation_raises():
    """Verify that proposed green violating bounds in validate_plan raises UnsafeStateError."""
    p1 = SignalPhase(id=1, signal_id=10, intersection_id=5, name="NB Thru", phase_order=1, is_active=True)
    p2 = SignalPhase(id=2, signal_id=10, intersection_id=5, name="EB Thru", phase_order=2, is_active=True)
    config = CycleConfig(min_green_s=10.0, max_green_s=60.0)

    # Proposed green 5.0s < min 10.0s
    with pytest.raises(UnsafeStateError, match="violates safety bounds"):
        SafetyValidator.validate_plan(
            intersection_id=5,
            proposed_greens={1: 5.0, 2: 30.0},
            phases=[p1, p2],
            config=config,
        )


def test_validate_plan_concurrent_conflict_in_plan_raises():
    """Verify that concurrent green phases in same phase_order that conflict raise UnsafeStateError."""
    # Two phases scheduled with the same phase_order 1 (running concurrently)
    p_nb = SignalPhase(id=1, signal_id=10, intersection_id=5, name="Northbound Through", phase_order=1, is_active=True)
    p_eb = SignalPhase(id=2, signal_id=10, intersection_id=5, name="Eastbound Through", phase_order=1, is_active=True)
    config = CycleConfig(min_green_s=10.0, max_green_s=60.0)

    with pytest.raises(UnsafeStateError, match="Phase conflict detected"):
        SafetyValidator.validate_plan(
            intersection_id=5,
            proposed_greens={1: 25.0, 2: 25.0},
            phases=[p_nb, p_eb],
            config=config,
        )


def test_validate_plan_currently_conflicting_green_states_raises():
    """Verify that if phases in database are currently both observed green and conflict, validate_plan raises."""
    p_nb = SignalPhase(id=1, signal_id=10, intersection_id=5, name="Northbound Through", phase_order=1, is_active=True, state="green")
    p_eb = SignalPhase(id=2, signal_id=10, intersection_id=5, name="Eastbound Through", phase_order=2, is_active=True, state="green")
    config = CycleConfig(min_green_s=10.0, max_green_s=60.0)

    with pytest.raises(UnsafeStateError, match="Phase conflict detected"):
        SafetyValidator.validate_plan(
            intersection_id=5,
            proposed_greens={1: 25.0, 2: 25.0},
            phases=[p_nb, p_eb],
            config=config,
        )
