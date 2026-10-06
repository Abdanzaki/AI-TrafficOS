"""Travel time and generalized impedance cost calculations.

Implements traffic-engineering cost functions for routing algorithms, accounting for
free-flow travel time, congestion delay factors, roadway functional hierarchy friction,
and multi-attribute generalized cost profiles.
"""

from dataclasses import dataclass

from app.services.routing.graph import Edge


@dataclass
class CostProfile:
    """Weighting parameters for generalized routing travel cost formulation.

    Attributes:
        time_weight: Multiplier on congested travel time (dimensionless, default 1.0).
            Governs sensitivity to in-vehicle travel time.
        distance_weight: Cost penalty per unit distance (minutes / km, default 0.15).
            Represents generalized distance-proportional operating costs, fuel/energy
            consumption, and vehicle wear-and-tear converted into equivalent minutes.
        congestion_weight: Multiplier on congestion-induced delay (dimensionless, default 1.0).
            Provides independent calibration for traveler aversion to stop-and-go delays.
        condition_weight: Multiplier on functional class friction delay (dimensionless, default 0.5).
            Penalizes routing choices through lower-order road hierarchies (e.g. residential streets).
    """

    time_weight: float = 1.0
    distance_weight: float = 0.15
    congestion_weight: float = 1.0
    condition_weight: float = 0.5

    def __post_init__(self) -> None:
        """Ensure all cost weights are non-negative."""
        if (
            self.time_weight < 0
            or self.distance_weight < 0
            or self.congestion_weight < 0
            or self.condition_weight < 0
        ):
            raise ValueError("CostProfile weights cannot be negative")


def free_flow_time_minutes(edge: Edge) -> float:
    """Calculate unimpeded traversal time in minutes at the posted speed limit.

    Formula:
        (length_km / speed_limit_kmh) * 60

    Traffic-engineering rationale:
        Represents baseline travel duration under free-flow conditions where
        traffic density is near zero, meaning vehicles operate at the legal design
        speed without queuing or signal delay.

    Raises:
        ValueError: If edge.length_km is negative or speed_limit_kmh is non-positive.
    """
    if edge.length_km < 0:
        raise ValueError(f"Edge length_km cannot be negative: {edge.length_km}")
    if edge.speed_limit_kmh <= 0:
        raise ValueError(f"Edge speed_limit_kmh must be positive: {edge.speed_limit_kmh}")
    return (edge.length_km / edge.speed_limit_kmh) * 60.0


def congestion_factor(level_0_to_100: float) -> float:
    """Calculate the travel time multiplier for a given congestion level (0 to 100).

    Formula:
        1.0 + (level / 100.0) * 2.0

    Traffic-engineering rationale:
        Under free-flow (0% congestion), the factor is 1.0 (no added delay).
        At 100% congestion (complete saturation / gridlock), the factor reaches 3.0,
        tripling free-flow travel time. This aligns with empirical urban transport
        observations where dense stop-and-go queuing typically triples traversal latency
        relative to uncongested operations.

    Raises:
        ValueError: If level_0_to_100 is negative.
    """
    if level_0_to_100 < 0:
        raise ValueError(f"Congestion level cannot be negative: {level_0_to_100}")
    clamped = min(100.0, float(level_0_to_100))
    return 1.0 + (clamped / 100.0) * 2.0


def condition_factor(road_type: str) -> float:
    """Calculate the road functional classification impedance factor.

    Hierarchy mapping:
        - 'arterial': 1.0 (high capacity, coordinated traffic signals, minimal access points)
        - 'collector': 1.1 (moderate capacity, channelized turning, intermittent signals)
        - 'local': 1.25 (frequent unsignalized cross-streets, pedestrian friction, parking maneuvers)
        - unknown/other: 1.15 (conservative baseline impedance)

    Traffic-engineering rationale:
        Lower-order roadway classes introduce geometric friction, frequent unsignalized driveways,
        pedestrian crossings, and traffic-calming measures that impede steady vehicular flow.
        Penalizing lower-order roads ensures routing engines prioritize high-capacity arterials over
        residential neighborhoods unless significant congestion justifies diversion.
    """
    norm = (road_type or "").strip().lower()
    if norm == "arterial":
        return 1.0
    elif norm == "collector":
        return 1.1
    elif norm == "local":
        return 1.25
    return 1.15


def edge_cost(
    edge: Edge,
    congestion_level: float,
    profile: CostProfile = CostProfile(),
) -> float:
    """Compute generalized traversal cost in equivalent minutes.

    Formula:
        generalized_minutes = (
            time_weight * free_flow * congestion_factor
            + distance_weight * length_km
            + condition_weight * (condition_factor - 1.0) * free_flow
        )

    Traffic-engineering rationale:
        Synthesizes three core components of transport impedance:
        1. Travel time component: Free-flow time scaled by instantaneous traffic congestion.
        2. Distance component: Distance-proportional vehicle operating cost penalty.
        3. Road class friction: Extra delay imposed by lower-classification road friction.

    Parameters:
        edge: Directed edge representing the roadway corridor segment.
        congestion_level: Current congestion percentage (clamped to [0, 100]).
        profile: CostProfile configuring relative weights of cost components.

    Returns:
        float: Generalized traversal cost expressed in equivalent minutes.

    Raises:
        ValueError: If edge physical attributes or profile weights are negative.
    """
    if edge.length_km < 0:
        raise ValueError(f"Edge length_km cannot be negative: {edge.length_km}")
    if edge.speed_limit_kmh <= 0:
        raise ValueError(f"Edge speed_limit_kmh must be positive: {edge.speed_limit_kmh}")
    if (
        profile.time_weight < 0
        or profile.distance_weight < 0
        or profile.congestion_weight < 0
        or profile.condition_weight < 0
    ):
        raise ValueError("CostProfile weights cannot be negative")

    clamped_congestion = max(0.0, min(100.0, float(congestion_level)))
    free_flow = free_flow_time_minutes(edge)
    cong_factor = congestion_factor(clamped_congestion)
    cond_factor = condition_factor(edge.road_type)

    return (
        profile.time_weight * free_flow * cong_factor
        + profile.distance_weight * edge.length_km
        + profile.condition_weight * (cond_factor - 1.0) * free_flow
    )
