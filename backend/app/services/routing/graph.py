"""Graph data structures for the AI TrafficOS road network.

Provides topological primitives (Edge and RoadGraph) modeling intersections as
nodes and roadway corridors as directed arcs with traffic-engineering attributes.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Edge:
    """Directed roadway segment connecting two topological intersection nodes.

    Traffic-engineering rationale:
        In macroscopic and microscopic transport network models, physical roads
        are decomposed into directed arcs representing permissible vehicular
        flow vectors between junction decision nodes. Attributes like length,
        operating speed limit, and capacity govern link latency and congestion
        impedance under dynamic traffic assignment.
    """

    road_id: int
    from_id: int
    to_id: int
    length_km: float
    speed_limit_kmh: float = 50.0
    road_type: str = "local"
    capacity_veh_per_hr: Optional[int] = None
    bidirectional: bool = True

    def __post_init__(self) -> None:
        """Validate edge physical invariants."""
        if self.length_km < 0:
            raise ValueError(f"Edge length_km cannot be negative: {self.length_km}")
        if self.speed_limit_kmh <= 0:
            raise ValueError(f"Edge speed_limit_kmh must be positive: {self.speed_limit_kmh}")


class RoadGraph:
    """Adjacency-list directed graph representation of the municipal road network.

    Traffic-engineering rationale:
        Graph-theoretic abstraction enables fast shortest-path routing (Dijkstra, A*),
        incident diversion calculation, emergency vehicle green-corridor dispatch,
        and equilibrium flow assignment. Nodes correspond to junctions/intersections,
        while edges represent channelized roadway links with flow capacities and delay costs.
    """

    def __init__(self) -> None:
        """Initialize an empty road network graph."""
        self.adjacency: dict[int, list[Edge]] = {}

    def add_node(self, node_id: int) -> None:
        """Register an intersection node in the network graph if not already present."""
        if node_id not in self.adjacency:
            self.adjacency[node_id] = []

    def add_edge(self, edge: Edge) -> None:
        """Insert a roadway edge into the network topology.

        Bidirectional corridors are expanded into two directed edges (forward
        from_id -> to_id and reverse to_id -> from_id), both preserving the parent
        road_id.

        Raises:
            ValueError: If edge.length_km is negative.
        """
        if edge.length_km < 0:
            raise ValueError(f"Edge length_km cannot be negative: {edge.length_km}")

        self.add_node(edge.from_id)
        self.add_node(edge.to_id)

        # Forward directed arc
        forward_edge = Edge(
            road_id=edge.road_id,
            from_id=edge.from_id,
            to_id=edge.to_id,
            length_km=edge.length_km,
            speed_limit_kmh=edge.speed_limit_kmh,
            road_type=edge.road_type,
            capacity_veh_per_hr=edge.capacity_veh_per_hr,
            bidirectional=edge.bidirectional,
        )
        self.adjacency[edge.from_id].append(forward_edge)

        # Reverse directed arc for bidirectional corridors
        if edge.bidirectional and edge.from_id != edge.to_id:
            reverse_edge = Edge(
                road_id=edge.road_id,
                from_id=edge.to_id,
                to_id=edge.from_id,
                length_km=edge.length_km,
                speed_limit_kmh=edge.speed_limit_kmh,
                road_type=edge.road_type,
                capacity_veh_per_hr=edge.capacity_veh_per_hr,
                bidirectional=edge.bidirectional,
            )
            self.adjacency[edge.to_id].append(reverse_edge)

    def neighbors(self, node_id: int) -> list[Edge]:
        """Return all outgoing directed edges incident from node_id."""
        return list(self.adjacency.get(node_id, []))

    def node_ids(self) -> list[int]:
        """Return list of all registered intersection node identifiers."""
        return list(self.adjacency.keys())

    def edge_count(self) -> int:
        """Return total count of directed edges across all nodes in the network graph."""
        return sum(len(edges) for edges in self.adjacency.values())

    def get_edge(self, from_id: int, to_id: int) -> Optional[Edge]:
        """Retrieve the directed edge between from_id and to_id, or None if none exists."""
        for edge in self.adjacency.get(from_id, []):
            if edge.to_id == to_id:
                return edge
        return None
