"""Emergency vehicle green-corridor route planning and signal preemption services.

Calculates optimal emergency routing trajectories and coordinates downstream
traffic signal controllers to hold or extend green phases along the transit path.
"""

from collections import defaultdict
from dataclasses import dataclass
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.signal import Signal, SignalPhase
from app.services.routing.costs import condition_factor
from app.services.routing.graph import Edge, RoadGraph
from app.services.routing.paths import astar


@dataclass
class CorridorSignalAction:
    """Preemption or monitoring instruction for a signal controller along the green corridor.

    Traffic-engineering rationale:
        Coordinated corridor clearance requires discrete control actions at each junction:
        - 'extend_green': Actively extends or preempts signal phase timing to grant continuous
          right-of-way through the junction until the emergency vehicle clears.
        - 'preempt': Immediate phase transition to clear conflicting pedestrian/vehicular flows.
        - 'monitor': Observational status for unsignalized junctions or nodes without automated
          hardware, relying on manual driver clearance and intersection yield rules.

    Attributes:
        intersection_id: Junction identifier where the signal action is designated.
        signal_id: Database identifier of the traffic signal controller, or None if unsignalized.
        action: Operational directive ('extend_green', 'preempt', or 'monitor').
        duration_seconds: Time interval the phase extension/preemption should remain active.
        reason: Justification describing timing parameters and nominal phase settings.
    """

    intersection_id: int
    signal_id: Optional[int]
    action: str
    duration_seconds: float
    reason: str

    def __post_init__(self) -> None:
        """Validate signal action attributes."""
        valid_actions = {"extend_green", "preempt", "monitor"}
        if self.action not in valid_actions:
            raise ValueError(f"Invalid corridor signal action '{self.action}', must be one of {valid_actions}")
        if self.duration_seconds < 0:
            raise ValueError(f"Signal action duration cannot be negative: {self.duration_seconds}")


@dataclass
class GreenCorridorPlan:
    """Coordinated green-wave dispatch plan for an emergency vehicle transit.

    Attributes:
        corridor_id: Unique UUID string identifying this corridor plan.
        path: Ordered list of intersection node identifiers from origin to destination.
        edges: Traversed directed roadway edges along the green wave path.
        signal_actions: List of CorridorSignalAction directives ordered along the transit path.
        estimated_minutes: Unimpeded transit duration at emergency operating speed.
        from_intersection_id: Origin junction identifier.
        to_intersection_id: Destination junction identifier.
    """

    corridor_id: str
    path: list[int]
    edges: list[Edge]
    signal_actions: list[CorridorSignalAction]
    estimated_minutes: float
    from_intersection_id: int
    to_intersection_id: int


async def plan_green_corridor(
    session: AsyncSession,
    graph: RoadGraph,
    road_congestion: dict[int, float],
    node_coords: dict[int, tuple[float, float]],
    from_intersection_id: int,
    to_intersection_id: int,
    emergency_speed_kmh: float = 60.0,
) -> GreenCorridorPlan:
    """Plan an emergency green wave preemption corridor between two intersections.

    Traffic-engineering rationale:
        Emergency vehicles equipped with visual beacons and sirens bypass ordinary
        congested queuing, rendering civilian congestion factors negligible.
        Consequently, route traversal latency is computed at authorized emergency operating
        speed (emergency_speed_kmh). However, roadway functional hierarchy still dictates
        geometric navigability (narrow residential streets feature tight turning radii,
        curbside parking, and pedestrian friction). A road-class friction penalty via
        condition_factor steers the A* pathfinder toward wide, multi-lane arterial corridors.

        Along the selected trajectory, downstream traffic signals are scheduled with
        'extend_green' actions. The extension duration matches cumulative vehicle arrival
        ETA plus a 20-second safety clearance buffer, preventing intersection gridlock
        and cross-traffic collisions during emergency transit.

    Parameters:
        session: Active asynchronous database session for signal hardware queries.
        graph: Hydrated RoadGraph instance representing the municipal network.
        road_congestion: Real-time road congestion mapping (discounted for emergency routing).
        node_coords: Geographical coordinates mapping (intersection_id -> (lat, lon)).
        from_intersection_id: Starting intersection identifier.
        to_intersection_id: Target destination intersection identifier.
        emergency_speed_kmh: Target cruising speed for the emergency vehicle in km/h.

    Returns:
        GreenCorridorPlan containing routing path, edge sequence, signal control actions, and ETA.

    Raises:
        ValueError: If emergency_speed_kmh <= 0 or endpoints are invalid.
        NoPathError: If destination cannot be reached.
    """
    if emergency_speed_kmh <= 0:
        raise ValueError(f"emergency_speed_kmh must be positive: {emergency_speed_kmh}")

    def emergency_cost_fn(edge: Edge) -> float:
        """Evaluate emergency impedance: free-flow time at emergency speed + hierarchy friction."""
        base_minutes = (edge.length_km / emergency_speed_kmh) * 60.0
        cond = condition_factor(edge.road_type)
        friction = (cond - 1.0) * base_minutes
        return base_minutes + friction

    # Solve optimal emergency corridor trajectory using A* with spatial heuristic
    route_result = astar(
        graph=graph,
        source=from_intersection_id,
        target=to_intersection_id,
        cost_fn=emergency_cost_fn,
        coords=node_coords,
    )

    # Physical transit duration sum without friction weighting
    estimated_minutes = sum(
        (edge.length_km / emergency_speed_kmh) * 60.0 for edge in route_result.edges
    )

    # Compute cumulative ETA in seconds to each junction along the corridor path
    junction_eta: dict[int, float] = {}
    current_eta = 0.0
    if route_result.path:
        junction_eta[route_result.path[0]] = 0.0
        for i, edge in enumerate(route_result.edges):
            traversal_sec = (edge.length_km / emergency_speed_kmh) * 3600.0
            current_eta += traversal_sec
            next_junction = route_result.path[i + 1]
            junction_eta[next_junction] = current_eta

    signal_actions: list[CorridorSignalAction] = []

    if route_result.path:
        # Batched Query 1: Retrieve all signals installed at junctions on the corridor path
        sig_stmt = (
            select(Signal)
            .where(Signal.intersection_id.in_(route_result.path))
            .order_by(Signal.intersection_id, Signal.id)
        )
        sig_res = await session.execute(sig_stmt)
        signals = sig_res.scalars().all()

        signals_by_junction: dict[int, list[Signal]] = defaultdict(list)
        for sig in signals:
            signals_by_junction[sig.intersection_id].append(sig)

        # Batched Query 2: Retrieve all signal phases for the queried signals (Zero N+1)
        signal_ids = [s.id for s in signals]
        phases_by_signal: dict[int, list[SignalPhase]] = defaultdict(list)
        if signal_ids:
            phase_stmt = (
                select(SignalPhase)
                .where(SignalPhase.signal_id.in_(signal_ids))
                .order_by(SignalPhase.signal_id, SignalPhase.phase_order)
            )
            phase_res = await session.execute(phase_stmt)
            phases = phase_res.scalars().all()
            for phase in phases:
                phases_by_signal[phase.signal_id].append(phase)

        # Generate signal directives for each junction on the corridor path
        for junction_id in route_result.path:
            j_signals = signals_by_junction.get(junction_id, [])
            eta_seconds = junction_eta.get(junction_id, 0.0)

            if not j_signals:
                signal_actions.append(
                    CorridorSignalAction(
                        intersection_id=junction_id,
                        signal_id=None,
                        action="monitor",
                        duration_seconds=0.0,
                        reason="no signal hardware at junction",
                    )
                )
            else:
                for sig in j_signals:
                    sig_phases = phases_by_signal.get(sig.id, [])
                    green_phase = next(
                        (p for p in sig_phases if p.state.lower() == "green"),
                        None,
                    )
                    green_dur = (
                        green_phase.duration_seconds
                        if green_phase
                        else (sig_phases[0].duration_seconds if sig_phases else 30)
                    )
                    duration_sec = round(eta_seconds + 20.0, 2)
                    reason_msg = (
                        f"Extend green phase (nominal green: {green_dur}s) "
                        f"to {duration_sec}s for emergency clearance (+20s buffer)"
                    )
                    signal_actions.append(
                        CorridorSignalAction(
                            intersection_id=junction_id,
                            signal_id=sig.id,
                            action="extend_green",
                            duration_seconds=duration_sec,
                            reason=reason_msg,
                        )
                    )

    return GreenCorridorPlan(
        corridor_id=str(uuid.uuid4()),
        path=route_result.path,
        edges=route_result.edges,
        signal_actions=signal_actions,
        estimated_minutes=estimated_minutes,
        from_intersection_id=from_intersection_id,
        to_intersection_id=to_intersection_id,
    )
