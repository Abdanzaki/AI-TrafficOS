"""Comprehensive safety validation service for intelligent traffic control (Phase 6 Part 2).

CRITICAL ARCHITECTURAL SAFETY INVARIANT:
----------------------------------------
This validator serves as the authoritative safety gateway preventing any unsafe,
non-compliant, or physically hazardous signal timing proposal from exiting the
decision engine.

Under no circumstances may an unvalidated plan, invalid phase transition,
dilemma-zone timing violation, conflicting concurrent green state, or stale
telemetry recommendation be emitted.

DOCUMENTED HEURISTIC LIMITATIONS:
---------------------------------
In field-hardened NEMA TS-2 or Type 170/2070 traffic signal controller cabinets,
safety interlocks are enforced in hardware by a certified Malfunction Management
Unit (MMU) or Conflict Monitor Unit (CMU) wired with a physical channel diode card
or programmed conflict matrix.

Pending a dedicated relational conflict-matrix schema, the conflict detection in
`check_conflicts` implements a conservative heuristic based on phase name parsing:
1. Opposing straight/through movements on the same physical axis (e.g. Northbound
   Through vs. Southbound Through; Eastbound Through vs. Westbound Through) and dual
   opposing left-turn movements (e.g. NB Left + SB Left) are recognized as compatible.
2. Movements lacking identifiable directional tokens or spanning crossing axes
   (e.g., North-South vs. East-West) are conservatively classified as CONFLICTING.
3. Explicit compatibility markers (e.g., containing 'compatible_with:<target>') in
   phase names are respected.
Any pair that cannot be proven compatible strictly raises UnsafeStateError.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import itertools
import re
from typing import Any, Optional, Sequence

from app.models.signal import SignalPhase
from app.services.control.exceptions import StaleTelemetryError, UnsafeStateError
from app.services.control.optimization import CycleConfig


@dataclass(frozen=True)
class ValidatedPlan:
    """Safety-certified signal timing plan approved for supervisory proposal.

    Attributes:
        intersection_id: Identifier of the junction to which the plan applies.
        proposed_greens: Per-phase allocated green durations in seconds {phase_id: green_s}.
        is_valid: Safety assertion flag (permanently True when successfully validated).
        validated_at: Timestamp in UTC when validation passed.
        total_cycle_s: Calculated total cycle length in seconds.
    """

    intersection_id: int
    proposed_greens: dict[int, float]
    is_valid: bool = True
    validated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    total_cycle_s: Optional[float] = None


def _parse_movement_hint(phase_name: str) -> dict[str, Any]:
    """Parse phase name for directional axis, movement type, and compatibility markers.

    Args:
        phase_name: Raw name string from SignalPhase model.

    Returns:
        Dictionary containing extracted direction, movement type, and explicit tags.
    """
    name_clean = phase_name.strip()
    name_lower = name_clean.lower()

    # 1. Explicit compatibility markers: compatible_with:<marker>
    compatible_targets: set[str] = set()
    matches = re.findall(r"compatible_with:([a-zA-Z0-9_\-]+)", name_lower)
    for m in matches:
        compatible_targets.add(m.strip())

    # 2. Direction detection (North, South, East, West)
    direction: Optional[str] = None
    if (
        re.search(r"\b(northbound|north|nb)\b", name_lower)
        or re.search(r"^nb[_\-\s]", name_lower)
        or "_nb" in name_lower
        or "(nb" in name_lower
        or "nbl" in name_lower
        or "nbr" in name_lower
        or "n_thru" in name_lower
    ):
        direction = "north"
    elif (
        re.search(r"\b(southbound|south|sb)\b", name_lower)
        or re.search(r"^sb[_\-\s]", name_lower)
        or "_sb" in name_lower
        or "(sb" in name_lower
        or "sbl" in name_lower
        or "sbr" in name_lower
        or "s_thru" in name_lower
    ):
        direction = "south"
    elif (
        re.search(r"\b(eastbound|east|eb)\b", name_lower)
        or re.search(r"^eb[_\-\s]", name_lower)
        or "_eb" in name_lower
        or "(eb" in name_lower
        or "ebl" in name_lower
        or "ebr" in name_lower
        or "e_thru" in name_lower
    ):
        direction = "east"
    elif (
        re.search(r"\b(westbound|west|wb)\b", name_lower)
        or re.search(r"^wb[_\-\s]", name_lower)
        or "_wb" in name_lower
        or "(wb" in name_lower
        or "wbl" in name_lower
        or "wbr" in name_lower
        or "w_thru" in name_lower
    ):
        direction = "west"

    # 3. Movement classification (left, right, through)
    movement: str = "through"  # Default assumption for directional phases
    if (
        re.search(r"\b(left|lt|l_turn|turning_left)\b", name_lower)
        or any(tok in name_lower for tok in ["_left", "nbl", "sbl", "ebl", "wbl"])
    ):
        movement = "left"
    elif (
        re.search(r"\b(right|rt|r_turn|turning_right)\b", name_lower)
        or any(tok in name_lower for tok in ["_right", "nbr", "sbr", "ebr", "wbr"])
    ):
        movement = "right"
    elif (
        re.search(r"\b(thru|through|straight|str)\b", name_lower)
        or any(tok in name_lower for tok in ["_thru", "_straight"])
    ):
        movement = "through"

    return {
        "direction": direction,
        "movement": movement,
        "compatible_targets": compatible_targets,
        "raw_lower": name_lower,
    }


def _are_movements_compatible(
    p1_info: dict[str, Any],
    p2_info: dict[str, Any],
) -> bool:
    """Evaluate whether two parsed phase movements are safe to display green concurrently.

    Args:
        p1_info: Parsed movement dictionary for first phase.
        p2_info: Parsed movement dictionary for second phase.

    Returns:
        True if movements are proven compatible; False if conflicting.
    """
    raw1 = p1_info["raw_lower"]
    raw2 = p2_info["raw_lower"]

    # Check 1: Explicit bidirectional compatibility markers
    if any(t in raw2 for t in p1_info["compatible_targets"]):
        return True
    if any(t in raw1 for t in p2_info["compatible_targets"]):
        return True
    shared_targets = p1_info["compatible_targets"].intersection(p2_info["compatible_targets"])
    if shared_targets:
        return True

    d1 = p1_info["direction"]
    d2 = p2_info["direction"]
    m1 = p1_info["movement"]
    m2 = p2_info["movement"]

    # Rule: Any phase lacking a verifiable directional token cannot be verified safe
    if not d1 or not d2:
        return False

    # Rule: Same approach / identical direction
    if d1 == d2:
        return True

    # Rule: Opposing directions along North-South arterial axis
    if {d1, d2} == {"north", "south"}:
        # Opposing through / straight (or through + right) movements are compatible
        if m1 in ("through", "right") and m2 in ("through", "right"):
            return True
        # Dual protected left-turns (e.g. NB Left + SB Left) are compatible
        if m1 == "left" and m2 == "left":
            return True
        # An opposing left turn cutting across a through movement is a severe conflict
        return False

    # Rule: Opposing directions along East-West arterial axis
    if {d1, d2} == {"east", "west"}:
        # Opposing through / straight (or through + right) movements are compatible
        if m1 in ("through", "right") and m2 in ("through", "right"):
            return True
        # Dual protected left-turns (e.g. EB Left + WB Left) are compatible
        if m1 == "left" and m2 == "left":
            return True
        # An opposing left turn cutting across a through movement is a severe conflict
        return False

    # Crossing perpendicular movements (North-South vs East-West) are always conflicting
    return False


class SafetyValidator:
    """Rigorous supervisory safety validator for traffic signal control proposals."""

    @staticmethod
    def validate_timing(
        signal_id: int,
        phase_id: int,
        proposed_green_s: float,
        config: CycleConfig,
    ) -> None:
        """Validate that proposed green duration satisfies statutory safety bounds.

        SAFETY INVARIANT & HAZARD PREVENTED:
        ------------------------------------
        1. Prevents dilemma-zone and perception-reaction hazards: If green time is
           shorter than `min_green_s`, drivers approaching the stop bar may be caught
           in an indecision dilemma zone when the light turns yellow abruptly, or
           pedestrians may be trapped mid-crossing without adequate walk clearance.
        2. Prevents cross-traffic starvation and driver violation hazards: If green
           time exceeds `max_green_s`, cross-street traffic is starved of right-of-way,
           inducing driver impatience, excessive queue spillback, and red-light running.

        Args:
            signal_id: Controller identifier.
            phase_id: Unique phase identifier.
            proposed_green_s: Proposed green interval duration in seconds.
            config: Operational CycleConfig containing min_green_s and max_green_s.

        Raises:
            UnsafeStateError: If proposed_green_s is strictly less than min_green_s
                or strictly greater than max_green_s.
        """
        if proposed_green_s < config.min_green_s or proposed_green_s > config.max_green_s:
            raise UnsafeStateError(
                f"Proposed green time {proposed_green_s:.1f}s for phase {phase_id} "
                f"(signal {signal_id}) violates safety bounds [{config.min_green_s:.1f}s, {config.max_green_s:.1f}s]."
            )

    @staticmethod
    def validate_phase_transition(
        phases: Sequence[SignalPhase],
        from_phase_id: int,
        to_phase_id: int,
    ) -> None:
        """Enforce strict sequential cyclic progression and inactive phase lockout.

        SAFETY INVARIANT & HAZARD PREVENTED:
        ------------------------------------
        1. Prevents out-of-order phase jumping: Signal controllers must sequence through
           pre-defined ring/barrier phase sequences. Skipping phases disrupts driver
           expectations and short-circuits mandatory yellow change and all-red clearance
           intervals, risking catastrophic right-angle collisions.
        2. Prevents actuation of deactivated phases: Phases flagged `is_active=False`
           may represent heads under physical maintenance, defective load switches, or
           closed construction approaches. Directing right-of-way to an inactive phase
           invites immediate traffic chaos or worker injury.
        3. Permitted transitions:
           - Same phase (`from_phase_id == to_phase_id`): Valid green extension.
           - Next active phase in `phase_order` (wrapping cyclically from last to first).

        Args:
            phases: Sequence of SignalPhase ORM entities configured for the junction.
            from_phase_id: Identifier of the currently running phase.
            to_phase_id: Identifier of the candidate target phase.

        Raises:
            UnsafeStateError: If target phase is inactive, does not exist, or violates
                strict sequential cyclic order. Error message includes 'invalid phase transition'.
        """
        phase_map: dict[int, SignalPhase] = {p.id: p for p in phases}

        if to_phase_id not in phase_map:
            raise UnsafeStateError(
                f"invalid phase transition: destination phase {to_phase_id} does not exist in signal phases."
            )
        to_phase = phase_map[to_phase_id]

        # Inactive phases can never be transitioned to
        if not to_phase.is_active:
            raise UnsafeStateError(
                f"invalid phase transition: cannot transition to inactive phase {to_phase_id} ('{to_phase.name}')."
            )

        if from_phase_id not in phase_map:
            raise UnsafeStateError(
                f"invalid phase transition: origin phase {from_phase_id} does not exist in signal phases."
            )
        from_phase = phase_map[from_phase_id]

        # Case 1: Green extension on same active phase
        if from_phase_id == to_phase_id:
            return

        # Case 2: Advance to next active phase in cyclic phase_order
        active_phases = sorted(
            [p for p in phases if p.is_active],
            key=lambda p: (p.phase_order, p.id),
        )
        if not active_phases:
            raise UnsafeStateError("invalid phase transition: no active phases configured.")

        active_ids = [p.id for p in active_phases]
        if from_phase_id not in active_ids:
            raise UnsafeStateError(
                f"invalid phase transition: origin phase {from_phase_id} ('{from_phase.name}') is inactive."
            )

        from_idx = active_ids.index(from_phase_id)
        expected_next = active_phases[(from_idx + 1) % len(active_phases)]

        if to_phase_id != expected_next.id:
            raise UnsafeStateError(
                f"invalid phase transition: cannot transition from phase {from_phase_id} "
                f"('{from_phase.name}', order {from_phase.phase_order}) to phase {to_phase_id} "
                f"('{to_phase.name}', order {to_phase.phase_order}); expected next in sequence "
                f"is phase {expected_next.id} ('{expected_next.name}', order {expected_next.phase_order})."
            )

    @staticmethod
    def check_conflicts(
        phases: Sequence[SignalPhase],
        green_phase_ids: Sequence[int],
    ) -> None:
        """Prevent concurrent green indications on incompatible intersection approaches.

        SAFETY INVARIANT & HAZARD PREVENTED:
        ------------------------------------
        1. Prevents green-on-green collision states: Displaying green simultaneously to
           conflicting vehicular or pedestrian traffic streams results in direct
           perpendicular broadside (T-bone) or head-on turning collisions.
        2. Heuristic evaluation: Every pair of phases concurrently holding or proposed
           for green is checked. Two distinct phases are permitted concurrent green ONLY
           if their parsed movement hints demonstrate non-conflicting trajectories (e.g.
           dual North-South through movements, or explicit compatibility tags). Any
           conflicting pair immediately triggers an UnsafeStateError listing both phases.

        Args:
            phases: Sequence of SignalPhase ORM entities configured for the junction.
            green_phase_ids: List of phase IDs proposed or observed in green state.

        Raises:
            UnsafeStateError: If two conflicting phases are simultaneously green, listing
                the conflicting pair.
        """
        unique_green_ids = sorted(list(set(green_phase_ids)))
        if len(unique_green_ids) <= 1:
            return

        phase_map: dict[int, SignalPhase] = {p.id: p for p in phases}

        # Validate that all requested phases exist
        for pid in unique_green_ids:
            if pid not in phase_map:
                raise UnsafeStateError(
                    f"Phase {pid} in green_phase_ids does not exist in intersection phases."
                )

        # Check all unique pairs of concurrently green phases
        for p1_id, p2_id in itertools.combinations(unique_green_ids, 2):
            p1 = phase_map[p1_id]
            p2 = phase_map[p2_id]

            p1_info = _parse_movement_hint(p1.name)
            p2_info = _parse_movement_hint(p2.name)

            if not _are_movements_compatible(p1_info, p2_info):
                raise UnsafeStateError(
                    f"Phase conflict detected: phase {p1.id} ('{p1.name}') and phase {p2.id} "
                    f"('{p2.name}') cannot both be green concurrently. Potential right-angle collision hazard."
                )

    @staticmethod
    def ensure_no_action_on_stale(
        telemetry_age_s: float,
        max_age_s: float = 300.0,
        intersection_id: int = 0,
    ) -> None:
        """Guard against issuing signal timing changes based on stale sensor telemetry.

        SAFETY INVARIANT & HAZARD PREVENTED:
        ------------------------------------
        Prevents open-loop timing manipulation without live environmental feedback.
        If camera or loop-detector telemetry is older than `max_age_s`, queue dynamics
        may have shifted drastically (e.g. a queue cleared, an emergency vehicle arrived,
        or traffic halted due to an incident). Adjusting splits on stale data risks
        exacerbating congestion or trapping emergency responders.

        Args:
            telemetry_age_s: Elapsed time in seconds since the telemetry capture timestamp.
            max_age_s: Maximum permissible telemetry freshness threshold (default 300.0s).
            intersection_id: Identifier of the junction under inspection.

        Raises:
            StaleTelemetryError: If telemetry_age_s strictly exceeds max_age_s.
        """
        if telemetry_age_s > max_age_s:
            raise StaleTelemetryError(
                intersection_id=intersection_id,
                age_s=telemetry_age_s,
                max_telemetry_age_s=max_age_s,
            )

    @classmethod
    def validate_plan(
        cls,
        intersection_id: int,
        proposed_greens: dict[int, float],
        phases: Sequence[SignalPhase],
        config: CycleConfig,
    ) -> ValidatedPlan:
        """Perform comprehensive holistic validation of an entire proposed signal plan.

        SAFETY INVARIANT & HAZARD PREVENTED:
        ------------------------------------
        Guarantees that a complete cycle timing proposal satisfies all three safety
        dimensions before being surfaced to human operators or downstream systems:
        1. Timing Bounds: Every individual phase green duration adheres to [min_green_s, max_green_s].
        2. Phase Progression: All active phases form a valid, non-skipping cyclic sequence.
        3. Conflict Freedom: Neither observed active green phases nor scheduled concurrent
           phases present right-of-way conflicts.
        4. Inactive Isolation: Inactive phases receive zero green time.

        Args:
            intersection_id: Identifier of the junction.
            proposed_greens: Dictionary mapping phase_id to recommended green seconds.
            phases: Sequence of SignalPhase ORM entities configured for the junction.
            config: Operational CycleConfig containing bounds and clearance intervals.

        Returns:
            ValidatedPlan certification object.

        Raises:
            UnsafeStateError: If any safety check fails.
        """
        if not phases:
            raise UnsafeStateError(
                f"Plan validation failed: no signal phases configured for intersection {intersection_id}."
            )
        if not proposed_greens:
            raise UnsafeStateError(
                f"Plan validation failed: empty proposed green allocations for intersection {intersection_id}."
            )

        phase_map: dict[int, SignalPhase] = {p.id: p for p in phases}

        # 1. Validate timing bounds and inactive phase lockout
        for phase_id, green_s in proposed_greens.items():
            if phase_id not in phase_map:
                raise UnsafeStateError(
                    f"Proposed green allocation references nonexistent phase_id {phase_id} at intersection {intersection_id}."
                )
            phase = phase_map[phase_id]
            if not phase.is_active:
                raise UnsafeStateError(
                    f"Cannot allocate green time ({green_s:.1f}s) to inactive phase {phase_id} ('{phase.name}')."
                )
            cls.validate_timing(
                signal_id=phase.signal_id,
                phase_id=phase_id,
                proposed_green_s=green_s,
                config=config,
            )

        # 2. Validate cyclic phase transitions across active phases
        active_phases = sorted(
            [p for p in phases if p.is_active],
            key=lambda p: (p.phase_order, p.id),
        )
        if len(active_phases) >= 2:
            for i in range(len(active_phases)):
                cls.validate_phase_transition(
                    phases=phases,
                    from_phase_id=active_phases[i].id,
                    to_phase_id=active_phases[(i + 1) % len(active_phases)].id,
                )

        # 3. Conflict validation: Check currently green phases
        currently_green = [p.id for p in phases if str(p.state).lower() == "green"]
        if len(currently_green) > 1:
            cls.check_conflicts(phases=phases, green_phase_ids=currently_green)

        # 4. Conflict validation: Check concurrent phases sharing same phase_order in plan
        order_groups: dict[int, list[int]] = defaultdict(list)
        for p in active_phases:
            if p.id in proposed_greens and proposed_greens[p.id] > 0:
                order_groups[p.phase_order].append(p.id)

        for grp in order_groups.values():
            if len(grp) > 1:
                cls.check_conflicts(phases=phases, green_phase_ids=grp)

        # 5. Calculate total cycle time
        n_active = len(active_phases)
        total_cycle = sum(proposed_greens.values()) + n_active * (
            config.yellow_s + config.all_red_s
        )

        return ValidatedPlan(
            intersection_id=intersection_id,
            proposed_greens=dict(proposed_greens),
            is_valid=True,
            validated_at=datetime.now(timezone.utc),
            total_cycle_s=round(total_cycle, 2),
        )
