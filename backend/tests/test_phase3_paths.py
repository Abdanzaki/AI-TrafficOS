"""Unit tests for Phase 3 pathfinding algorithms and cost impedance functions.

Validates:
- Dijkstra correctness against exhaustive brute-force DFS path enumeration on random graphs.
- A* optimality and heuristic admissibility across identical random graphs.
- Robust handling of edge cases (unreachable targets, empty networks, self-loops, negative edge lengths,
  negative cost evaluations, and missing geographic coordinates).
- Haversine great-circle distance accuracy and sanity constraints.
- Free-flow time calculations, congestion factor scaling, road condition hierarchy, and CostProfile invariants.
"""

import math
import random
import pytest

from app.services.routing.costs import (
    CostProfile,
    condition_factor,
    congestion_factor,
    edge_cost,
    free_flow_time_minutes,
)
from app.services.routing.graph import Edge, RoadGraph
from app.services.routing.paths import (
    NoPathError,
    RouteResult,
    astar,
    dijkstra,
    haversine_km,
)


def _build_random_graph_and_coords(
    seed: int,
    num_nodes: int,
) -> tuple[RoadGraph, dict[int, tuple[float, float]], int, int]:
    """Generate a reproducible random connected graph with geographic coordinates.

    Ensures admissibility by placing nodes on a geographic plane and sizing edge physical
    lengths strictly greater than or equal to the straight-line Haversine distance between endpoints.
    """
    rng = random.Random(seed)
    graph = RoadGraph()

    # Generate node coordinates roughly in a 10 km bounding box around San Francisco
    base_lat, base_lon = 37.7749, -122.4194
    coords: dict[int, tuple[float, float]] = {}
    for i in range(num_nodes):
        graph.add_node(i)
        lat = base_lat + rng.uniform(-0.04, 0.04)
        lon = base_lon + rng.uniform(-0.04, 0.04)
        coords[i] = (lat, lon)

    # 1. Create a guaranteed directed path from 0 to num_nodes - 1 to ensure connectivity
    road_id_seq = 1
    permutation = list(range(num_nodes))
    source = permutation[0]
    target = permutation[-1]

    # Connect a Hamiltonian chain through the permutation
    for idx in range(len(permutation) - 1):
        u = permutation[idx]
        v = permutation[idx + 1]
        dist = haversine_km(coords[u][0], coords[u][1], coords[v][0], coords[v][1])
        # Actual road length is at least straight-line distance
        length = max(0.1, dist * rng.uniform(1.05, 1.35) + 0.05)
        speed = rng.choice([30.0, 45.0, 60.0, 80.0])
        road_type = rng.choice(["arterial", "collector", "local"])
        graph.add_edge(
            Edge(
                road_id=road_id_seq,
                from_id=u,
                to_id=v,
                length_km=length,
                speed_limit_kmh=speed,
                road_type=road_type,
                bidirectional=False,
            )
        )
        road_id_seq += 1

    # 2. Add additional random directed edges
    for _ in range(num_nodes * 2):
        u = rng.randint(0, num_nodes - 1)
        v = rng.randint(0, num_nodes - 1)
        if u == v or graph.get_edge(u, v) is not None:
            continue
        dist = haversine_km(coords[u][0], coords[u][1], coords[v][0], coords[v][1])
        length = max(0.1, dist * rng.uniform(1.05, 1.4) + 0.05)
        speed = rng.choice([30.0, 45.0, 60.0, 80.0])
        road_type = rng.choice(["arterial", "collector", "local"])
        graph.add_edge(
            Edge(
                road_id=road_id_seq,
                from_id=u,
                to_id=v,
                length_km=length,
                speed_limit_kmh=speed,
                road_type=road_type,
                bidirectional=False,
            )
        )
        road_id_seq += 1

    return graph, coords, source, target


def _exhaustive_dfs_min_cost(
    graph: RoadGraph,
    source: int,
    target: int,
    cost_fn,
) -> float:
    """Find minimum path cost by exhaustively enumerating all simple paths via DFS."""
    min_cost = float("inf")

    def dfs(curr: int, current_cost: float, visited: set[int]) -> None:
        nonlocal min_cost
        if curr == target:
            if current_cost < min_cost:
                min_cost = current_cost
            return

        for edge in graph.neighbors(curr):
            neighbor = edge.to_id
            if neighbor not in visited:
                cost = cost_fn(edge)
                visited.add(neighbor)
                dfs(neighbor, current_cost + cost, visited)
                visited.remove(neighbor)

    dfs(source, 0.0, {source})
    return min_cost


# ==============================================================================
# 1. Dijkstra Correctness vs Brute-Force DFS
# ==============================================================================

def test_dijkstra_correctness_vs_brute_force_dfs():
    """Verify Dijkstra against exhaustive DFS path enumeration on 20 random graphs (6-10 nodes)."""
    for seed in range(200, 220):
        num_nodes = random.Random(seed).randint(6, 10)
        graph, coords, source, target = _build_random_graph_and_coords(seed, num_nodes)

        # Standard free-flow travel time cost function
        cost_fn = free_flow_time_minutes

        min_dfs_cost = _exhaustive_dfs_min_cost(graph, source, target, cost_fn)
        assert min_dfs_cost < float("inf"), f"Graph seed {seed} should have a valid path"

        result = dijkstra(graph, source, target, cost_fn)

        assert isinstance(result, RouteResult)
        assert result.algorithm == "dijkstra"
        assert result.path[0] == source
        assert result.path[-1] == target
        assert len(result.edges) == len(result.path) - 1

        # Assert Dijkstra total cost equals brute-force minimum cost
        assert math.isclose(result.total_cost, min_dfs_cost, rel_tol=1e-6, abs_tol=1e-6), (
            f"Seed {seed}: Dijkstra cost {result.total_cost} != DFS min cost {min_dfs_cost}"
        )


# ==============================================================================
# 2. A* Optimality vs Dijkstra
# ==============================================================================

def test_astar_optimality_vs_dijkstra():
    """Verify A* search optimality matches Dijkstra on the same 20 random graphs with coordinates."""
    for seed in range(200, 220):
        num_nodes = random.Random(seed).randint(6, 10)
        graph, coords, source, target = _build_random_graph_and_coords(seed, num_nodes)

        cost_fn = free_flow_time_minutes

        dijkstra_res = dijkstra(graph, source, target, cost_fn)
        astar_res = astar(graph, source, target, cost_fn, coords)

        assert isinstance(astar_res, RouteResult)
        assert astar_res.algorithm == "astar"
        assert astar_res.path[0] == source
        assert astar_res.path[-1] == target

        # With an admissible heuristic, A* must find the exact optimal cost
        assert math.isclose(astar_res.total_cost, dijkstra_res.total_cost, rel_tol=1e-6, abs_tol=1e-6), (
            f"Seed {seed}: A* cost {astar_res.total_cost} != Dijkstra cost {dijkstra_res.total_cost}"
        )


# ==============================================================================
# 3. Pathfinding Edge Cases
# ==============================================================================

def test_disconnected_graph_raises_no_path_error():
    """A target unreachable from source must raise NoPathError in Dijkstra and A*."""
    graph = RoadGraph()
    graph.add_edge(Edge(road_id=1, from_id=1, to_id=2, length_km=1.0, bidirectional=False))
    graph.add_node(3)  # Isolated node

    with pytest.raises(NoPathError):
        dijkstra(graph, 1, 3, free_flow_time_minutes)

    coords = {1: (37.0, -122.0), 2: (37.01, -122.01), 3: (37.05, -122.05)}
    with pytest.raises(NoPathError):
        astar(graph, 1, 3, free_flow_time_minutes, coords)


def test_empty_graph_raises_value_error_for_unknown_nodes():
    """Querying nodes not present in the graph must raise ValueError."""
    graph = RoadGraph()
    with pytest.raises(ValueError, match="Source node 10 not present in graph"):
        dijkstra(graph, 10, 20, free_flow_time_minutes)

    graph.add_node(10)
    with pytest.raises(ValueError, match="Target node 20 not present in graph"):
        dijkstra(graph, 10, 20, free_flow_time_minutes)

    with pytest.raises(ValueError, match="Source node 99 not present in graph"):
        astar(graph, 99, 10, free_flow_time_minutes, {})


def test_single_node_graph_source_equals_target():
    """Querying source == target returns an empty edge list and 0.0 total cost."""
    graph = RoadGraph()
    graph.add_node(42)

    d_res = dijkstra(graph, 42, 42, free_flow_time_minutes)
    assert d_res.path == [42]
    assert d_res.edges == []
    assert d_res.total_cost == 0.0
    assert d_res.algorithm == "dijkstra"

    coords = {42: (37.7749, -122.4194)}
    a_res = astar(graph, 42, 42, free_flow_time_minutes, coords)
    assert a_res.path == [42]
    assert a_res.edges == []
    assert a_res.total_cost == 0.0
    assert a_res.algorithm == "astar"


def test_negative_edge_length_rejected():
    """Edge constructor must reject negative length_km with ValueError."""
    with pytest.raises(ValueError, match="cannot be negative"):
        Edge(road_id=1, from_id=1, to_id=2, length_km=-0.5)

    with pytest.raises(ValueError, match="must be positive"):
        Edge(road_id=1, from_id=1, to_id=2, length_km=1.0, speed_limit_kmh=0.0)


def test_negative_cost_fn_result_raises_value_error():
    """Negative cost returned by cost_fn during traversal must raise ValueError."""
    graph = RoadGraph()
    graph.add_edge(Edge(road_id=1, from_id=1, to_id=2, length_km=1.0, bidirectional=False))

    def bad_cost_fn(edge: Edge) -> float:
        return -10.0

    with pytest.raises(ValueError, match="Cost function returned negative cost"):
        dijkstra(graph, 1, 2, bad_cost_fn)

    coords = {1: (37.0, -122.0), 2: (37.01, -122.01)}
    with pytest.raises(ValueError, match="Cost function returned negative cost"):
        astar(graph, 1, 2, bad_cost_fn, coords)


def test_missing_coords_in_astar_degrades_gracefully():
    """Missing node coordinates in coords dictionary degrades heuristic to 0.0 while remaining optimal."""
    graph = RoadGraph()
    graph.add_edge(Edge(road_id=1, from_id=1, to_id=2, length_km=2.0, speed_limit_kmh=60.0))
    graph.add_edge(Edge(road_id=2, from_id=2, to_id=3, length_km=3.0, speed_limit_kmh=60.0))

    # Completely empty coords dictionary
    res_no_coords = astar(graph, 1, 3, free_flow_time_minutes, {})
    d_res = dijkstra(graph, 1, 3, free_flow_time_minutes)

    assert res_no_coords.path == [1, 2, 3]
    assert math.isclose(res_no_coords.total_cost, d_res.total_cost)

    # Missing target coords
    res_partial = astar(graph, 1, 3, free_flow_time_minutes, {1: (37.0, -122.0)})
    assert math.isclose(res_partial.total_cost, d_res.total_cost)

    # Missing source coords
    res_partial_target = astar(graph, 1, 3, free_flow_time_minutes, {3: (37.1, -122.1)})
    assert math.isclose(res_partial_target.total_cost, d_res.total_cost)


# ==============================================================================
# 4. Haversine Formula Sanity Checks
# ==============================================================================

def test_haversine_same_point():
    """Haversine distance between identical coordinates is zero."""
    assert haversine_km(37.7749, -122.4194, 37.7749, -122.4194) == 0.0
    assert haversine_km(0.0, 0.0, 0.0, 0.0) == 0.0


def test_haversine_known_city_pairs():
    """Haversine distance between known city pairs is accurate within 5%."""
    # Paris (48.8566 N, 2.3522 E) to London (51.5074 N, -0.1278 W) ~ 343 km
    paris_london = haversine_km(48.8566, 2.3522, 51.5074, -0.1278)
    expected_paris_london = 343.5
    assert abs(paris_london - expected_paris_london) / expected_paris_london < 0.02

    # New York (40.7128 N, -74.0060 W) to Los Angeles (34.0522 N, -118.2437 W) ~ 3936 km
    nyc_la = haversine_km(40.7128, -74.0060, 34.0522, -118.2437)
    expected_nyc_la = 3936.0
    assert abs(nyc_la - expected_nyc_la) / expected_nyc_la < 0.02


def test_haversine_invalid_coordinates_raise_value_error():
    """Out-of-bound geographic coordinates must raise ValueError."""
    with pytest.raises(ValueError, match="Latitude must be within"):
        haversine_km(91.0, 0.0, 0.0, 0.0)

    with pytest.raises(ValueError, match="Latitude must be within"):
        haversine_km(-95.0, 0.0, 0.0, 0.0)

    with pytest.raises(ValueError, match="Longitude must be within"):
        haversine_km(0.0, 185.0, 0.0, 0.0)

    with pytest.raises(ValueError, match="Longitude must be within"):
        haversine_km(0.0, 0.0, 0.0, -181.0)


# ==============================================================================
# 5. Cost Impedance Functions
# ==============================================================================

def test_free_flow_time_minutes_math():
    """Traversal time at posted speed limit: (length_km / speed_limit_kmh) * 60."""
    edge = Edge(road_id=1, from_id=1, to_id=2, length_km=60.0, speed_limit_kmh=60.0)
    assert free_flow_time_minutes(edge) == 60.0

    edge_100kmh = Edge(road_id=2, from_id=1, to_id=2, length_km=50.0, speed_limit_kmh=100.0)
    assert free_flow_time_minutes(edge_100kmh) == 30.0

    edge_short = Edge(road_id=3, from_id=1, to_id=2, length_km=0.5, speed_limit_kmh=30.0)
    assert free_flow_time_minutes(edge_short) == 1.0


def test_congestion_factor_scaling():
    """Congestion factor scaling: 0% -> 1.0, 50% -> 2.0, 100% -> 3.0."""
    assert congestion_factor(0) == 1.0
    assert congestion_factor(50) == 2.0
    assert congestion_factor(100) == 3.0

    # Values beyond 100 are clamped to 100 -> 3.0
    assert congestion_factor(150) == 3.0

    # Negative values raise ValueError
    with pytest.raises(ValueError, match="cannot be negative"):
        congestion_factor(-5.0)


def test_condition_factor_ordering():
    """Functional class friction ordering: arterial < collector < local."""
    c_art = condition_factor("arterial")
    c_col = condition_factor("collector")
    c_loc = condition_factor("local")
    c_other = condition_factor("unknown_highway")

    assert c_art == 1.0
    assert c_col == 1.1
    assert c_loc == 1.25
    assert c_art < c_col < c_loc
    assert c_other == 1.15


def test_cost_profile_validation():
    """CostProfile rejects negative weights with ValueError."""
    # Valid default
    p = CostProfile()
    assert p.time_weight == 1.0
    assert p.distance_weight == 0.15

    # Negative weights rejected
    with pytest.raises(ValueError, match="CostProfile weights cannot be negative"):
        CostProfile(time_weight=-0.1)

    with pytest.raises(ValueError, match="CostProfile weights cannot be negative"):
        CostProfile(distance_weight=-1.0)

    with pytest.raises(ValueError, match="CostProfile weights cannot be negative"):
        CostProfile(congestion_weight=-0.5)

    with pytest.raises(ValueError, match="CostProfile weights cannot be negative"):
        CostProfile(condition_weight=-0.2)


def test_edge_cost_synthesis():
    """Generalized edge_cost accurately synthesizes time, distance, and road hierarchy friction."""
    edge = Edge(
        road_id=1,
        from_id=1,
        to_id=2,
        length_km=10.0,
        speed_limit_kmh=60.0,
        road_type="local",
    )
    # free_flow = (10 / 60) * 60 = 10.0 minutes
    # congestion 50 -> factor 2.0 -> time cost = 1.0 * 10.0 * 2.0 = 20.0
    # distance cost = 0.15 * 10.0 = 1.5
    # condition factor = 1.25 -> extra friction = 0.5 * (1.25 - 1.0) * 10.0 = 1.25
    # total cost = 20.0 + 1.5 + 1.25 = 22.75
    profile = CostProfile(time_weight=1.0, distance_weight=0.15, condition_weight=0.5)
    cost = edge_cost(edge, congestion_level=50.0, profile=profile)
    assert math.isclose(cost, 22.75, abs_tol=1e-6)
