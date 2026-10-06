"""Shortest-path graph search algorithms for municipal road networks.

Provides topological routing implementations (Dijkstra and A*) operating on
RoadGraph networks with generalized traffic-engineering cost impedance functions
and admissible spatial distance heuristics.
"""

from collections.abc import Callable
from dataclasses import dataclass
import heapq
import math

from app.services.routing.graph import Edge, RoadGraph


class NoPathError(Exception):
    """Raised when no traversable topological path exists between source and target junctions."""


@dataclass
class RouteResult:
    """Optimal path search result across the road network topology.

    Traffic-engineering rationale:
        In dynamic traffic management, routing solutions must report both the node
        sequence (intersections where turning maneuvers or signal control occurs)
        and the directed edge sequence (road segments where link travel times,
        capacities, and congestion factors are evaluated).

    Attributes:
        path: Ordered list of topological intersection node identifiers.
        edges: Ordered list of traversed directed Edge segments.
        total_cost: Aggregated traversal impedance (e.g. generalized minutes).
        algorithm: String identifier of the pathfinding algorithm ('dijkstra' or 'astar').
    """

    path: list[int]
    edges: list[Edge]
    total_cost: float
    algorithm: str


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two geographic coordinates in kilometers.

    Traffic-engineering rationale:
        Computes great-circle spherical distance between junction locations,
        providing an admissible lower bound on physical roadway length.

    Parameters:
        lat1: Latitude of point 1 in decimal degrees [-90.0, 90.0].
        lon1: Longitude of point 1 in decimal degrees [-180.0, 180.0].
        lat2: Latitude of point 2 in decimal degrees [-90.0, 90.0].
        lon2: Longitude of point 2 in decimal degrees [-180.0, 180.0].

    Returns:
        float: Great-circle distance in kilometers.

    Raises:
        ValueError: If any coordinate lies outside physical geographic boundaries.
    """
    if not (-90.0 <= lat1 <= 90.0 and -90.0 <= lat2 <= 90.0):
        raise ValueError(f"Latitude must be within [-90.0, 90.0]: lat1={lat1}, lat2={lat2}")
    if not (-180.0 <= lon1 <= 180.0 and -180.0 <= lon2 <= 180.0):
        raise ValueError(f"Longitude must be within [-180.0, 180.0]: lon1={lon1}, lon2={lon2}")

    if lat1 == lat2 and lon1 == lon2:
        return 0.0

    # Mean Earth radius in kilometers (IUGG standard: 6371.0088 km)
    earth_radius_km = 6371.0088

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    )
    # Clamp to handle numerical floating point inaccuracies
    clamped_a = min(1.0, max(0.0, a))
    c = 2.0 * math.atan2(math.sqrt(clamped_a), math.sqrt(1.0 - clamped_a))

    return earth_radius_km * c


def dijkstra(
    graph: RoadGraph,
    source: int,
    target: int,
    cost_fn: Callable[[Edge], float],
) -> RouteResult:
    """Compute the minimum-cost route between source and target using Dijkstra's algorithm.

    Traffic-engineering rationale:
        Dijkstra's algorithm guarantees global optimality under arbitrary non-negative
        link impedance functions. It serves as the baseline shortest-path solver for
        multi-attribute routing where spatial heuristics may not be readily available.

    Parameters:
        graph: Hydrated RoadGraph instance modeling the network topology.
        source: Starting intersection identifier.
        target: Destination intersection identifier.
        cost_fn: Callable taking an Edge and returning a non-negative traversal impedance.

    Returns:
        RouteResult containing the optimal node path, edge sequence, and accumulated cost.

    Raises:
        ValueError: If source or target are not present in graph, or if cost_fn yields negative cost.
        NoPathError: If target cannot be reached from source.
    """
    if source not in graph.adjacency:
        raise ValueError(f"Source node {source} not present in graph")
    if target not in graph.adjacency:
        raise ValueError(f"Target node {target} not present in graph")

    if source == target:
        return RouteResult(
            path=[source],
            edges=[],
            total_cost=0.0,
            algorithm="dijkstra",
        )

    # Priority queue stores tuples: (accumulated_cost, sequence_counter, current_node)
    pq: list[tuple[float, int, int]] = []
    counter = 0
    heapq.heappush(pq, (0.0, counter, source))

    distances: dict[int, float] = {source: 0.0}
    predecessors: dict[int, tuple[int, Edge]] = {}
    visited: set[int] = set()

    while pq:
        cost, _, current = heapq.heappop(pq)

        if current in visited:
            continue
        visited.add(current)

        if current == target:
            break

        for edge in graph.neighbors(current):
            neighbor = edge.to_id
            edge_impedance = cost_fn(edge)
            if edge_impedance < 0:
                raise ValueError(
                    f"Cost function returned negative cost {edge_impedance} "
                    f"for edge from {edge.from_id} to {edge.to_id}"
                )

            new_cost = cost + edge_impedance
            if neighbor not in distances or new_cost < distances[neighbor]:
                distances[neighbor] = new_cost
                predecessors[neighbor] = (current, edge)
                counter += 1
                heapq.heappush(pq, (new_cost, counter, neighbor))

    if target not in visited:
        raise NoPathError(f"No path found between source node {source} and target node {target}")

    # Backtrack path and edge sequence from target to source
    path: list[int] = [target]
    edges: list[Edge] = []
    curr = target
    while curr != source:
        prev, edge_used = predecessors[curr]
        edges.append(edge_used)
        path.append(prev)
        curr = prev

    path.reverse()
    edges.reverse()

    return RouteResult(
        path=path,
        edges=edges,
        total_cost=distances[target],
        algorithm="dijkstra",
    )


def astar(
    graph: RoadGraph,
    source: int,
    target: int,
    cost_fn: Callable[[Edge], float],
    coords: dict[int, tuple[float, float]],
) -> RouteResult:
    """Compute the minimum-cost route using the A* heuristic search algorithm.

    Traffic-engineering rationale:
        A* accelerates shortest-path search by biasing exploration towards the target
        using an admissible heuristic. By estimating minimum physical free-flow travel
        time (straight-line Haversine distance divided by the maximum network speed limit),
        the heuristic is guaranteed never to overestimate the true link traversal cost
        in minutes. Nodes with missing coordinate records receive a heuristic estimate
        of 0.0, gracefully degrading to optimal Dijkstra search without sacrificing admissibility.

    Parameters:
        graph: Hydrated RoadGraph instance.
        source: Origin intersection identifier.
        target: Destination intersection identifier.
        cost_fn: Callable evaluating link traversal impedance for each Edge.
        coords: Mapping of intersection_id -> (latitude, longitude).

    Returns:
        RouteResult detailing path nodes, traversed edges, total cost, and 'astar' tag.

    Raises:
        ValueError: If source or target node not in graph, or cost_fn produces negative cost.
        NoPathError: If target is topologically unreachable from source.
    """
    if source not in graph.adjacency:
        raise ValueError(f"Source node {source} not present in graph")
    if target not in graph.adjacency:
        raise ValueError(f"Target node {target} not present in graph")

    if source == target:
        return RouteResult(
            path=[source],
            edges=[],
            total_cost=0.0,
            algorithm="astar",
        )

    # Determine maximum speed limit across all network edges to formulate admissible heuristic
    max_speed_kmh = 50.0
    all_edges = [edge for edge_list in graph.adjacency.values() for edge in edge_list]
    if all_edges:
        max_speed_kmh = max(edge.speed_limit_kmh for edge in all_edges)
    if max_speed_kmh <= 0:
        max_speed_kmh = 50.0

    target_has_coords = target in coords

    def heuristic(node_id: int) -> float:
        """Admissible lower-bound estimate in generalized travel time minutes."""
        if not target_has_coords or node_id not in coords:
            return 0.0
        lat1, lon1 = coords[node_id]
        lat2, lon2 = coords[target]
        dist_km = haversine_km(lat1, lon1, lat2, lon2)
        # Straight-line distance / max speed limit converted to minutes
        return (dist_km / max_speed_kmh) * 60.0

    # Heap contains tuples: (f_score, g_score, sequence_counter, current_node)
    pq: list[tuple[float, float, int, int]] = []
    counter = 0
    h_source = heuristic(source)
    heapq.heappush(pq, (h_source, 0.0, counter, source))

    g_scores: dict[int, float] = {source: 0.0}
    predecessors: dict[int, tuple[int, Edge]] = {}
    visited: set[int] = set()

    while pq:
        f_score, g_score, _, current = heapq.heappop(pq)

        if current in visited:
            continue
        visited.add(current)

        if current == target:
            break

        for edge in graph.neighbors(current):
            neighbor = edge.to_id
            edge_impedance = cost_fn(edge)
            if edge_impedance < 0:
                raise ValueError(
                    f"Cost function returned negative cost {edge_impedance} "
                    f"for edge from {edge.from_id} to {edge.to_id}"
                )

            tentative_g = g_score + edge_impedance
            if neighbor not in g_scores or tentative_g < g_scores[neighbor]:
                g_scores[neighbor] = tentative_g
                predecessors[neighbor] = (current, edge)
                counter += 1
                h_neighbor = heuristic(neighbor)
                heapq.heappush(pq, (tentative_g + h_neighbor, tentative_g, counter, neighbor))

    if target not in visited:
        raise NoPathError(f"No path found between source node {source} and target node {target}")

    # Reconstruct shortest path
    path = [target]
    edges = []
    curr = target
    while curr != source:
        prev, edge_used = predecessors[curr]
        edges.append(edge_used)
        path.append(prev)
        curr = prev

    path.reverse()
    edges.reverse()

    return RouteResult(
        path=path,
        edges=edges,
        total_cost=g_scores[target],
        algorithm="astar",
    )
