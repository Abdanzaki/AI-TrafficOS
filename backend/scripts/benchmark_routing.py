"""Routing performance benchmark: Dijkstra vs A* on synthetic road networks.

Evaluates shortest-path search latencies, algorithmic speedups, and path-cost
optimality across 1k-node and 10k-node synthetic grid topologies.

Usage:
    cd ~/workspace/AI-TrafficOS/backend && .venv/bin/python scripts/benchmark_routing.py
"""

import math
from pathlib import Path
import random
import sys
import time

# Ensure backend root is in sys.path for direct module imports
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.services.routing import Edge, RoadGraph, astar, dijkstra
from app.services.routing.costs import free_flow_time_minutes

# Mean Earth radius in kilometers (IUGG standard matching app.services.routing.paths.haversine_km)
EARTH_RADIUS_KM = 6371.0088
KM_PER_DEGREE = EARTH_RADIUS_KM * (math.pi / 180.0)  # ≈ 111.1949266 km per degree


def build_synthetic_grid(
    rows: int,
    cols: int,
    seed: int = 42,
) -> tuple[RoadGraph, dict[int, tuple[float, float]]]:
    """Construct a synthetic 2D grid road network with 4-neighbor connectivity.

    Topological Structure:
        - Nodes correspond to grid junctions indexed row-major: node_id = r * cols + c.
        - Each interior node has 4 directed outgoing edges (North, South, East, West).
        - Edge lengths are uniformly distributed in [0.5, 2.0] km.
        - Edge operating speeds are uniformly distributed in [30.0, 80.0] km/h.
        - All segments are assigned road_type='arterial'.

    Haversine Heuristic Planar Projection Approximation:
        In this benchmark, each node at grid index (r, c) has planar coordinates:
            x_km = float(c)
            y_km = float(r)
        treated as planar kilometers.
        The routing engine's astar algorithm expects geographic coordinates (lat, lon)
        in decimal degrees and computes great-circle distance via haversine_km().
        A naive assignment of (y_km, x_km) directly as decimal degrees would violate
        haversine_km's physical latitude domain check [-90.0, 90.0] for grids with
        dimension >= 91 (e.g. 100x100 grid reaching row 99).
        Furthermore, 1 degree of latitude is ~111.195 km, so unscaled coordinates would
        inflate heuristic distances by ~111x and destroy heuristic admissibility.
        To treat (x_km, y_km) as planar kilometers in a mathematically sound manner,
        we project them onto a local spherical reference frame centered at the equator
        (lat=0.0, lon=0.0):
            lat = y_km / KM_PER_DEGREE
            lon = x_km / KM_PER_DEGREE
        Because coordinates remain close to the equator (lat <= 99 / 111.195 ≈ 0.89°),
        haversine_km(lat1, lon1, lat2, lon2) closely approximates planar Euclidean distance:
            dist_km ≈ sqrt((x2 - x1)^2 + (y2 - y1)^2) in kilometers.
        This provides an admissible lower-bound distance heuristic for A* across planar space.
    """
    rng = random.Random(seed)
    graph = RoadGraph()
    coords: dict[int, tuple[float, float]] = {}

    # Register all intersection nodes with projected spherical coordinates
    for r in range(rows):
        for c in range(cols):
            node_id = r * cols + c
            graph.add_node(node_id)
            x_km = float(c)
            y_km = float(r)
            lat = y_km / KM_PER_DEGREE
            lon = x_km / KM_PER_DEGREE
            coords[node_id] = (lat, lon)

    # Instantiate directed edges with 4-neighbor connectivity
    edge_id = 1
    for r in range(rows):
        for c in range(cols):
            u = r * cols + c
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols:
                    v = nr * cols + nc
                    length_km = rng.uniform(0.5, 2.0)
                    speed_kmh = rng.uniform(30.0, 80.0)
                    edge = Edge(
                        road_id=edge_id,
                        from_id=u,
                        to_id=v,
                        length_km=length_km,
                        speed_limit_kmh=speed_kmh,
                        road_type="arterial",
                        bidirectional=False,
                    )
                    graph.add_edge(edge)
                    edge_id += 1

    return graph, coords


def benchmark_network(
    name: str,
    rows: int,
    cols: int,
    runs: int = 5,
    seed: int = 42,
) -> dict:
    """Benchmark Dijkstra vs A* on a synthetic grid network."""
    graph, coords = build_synthetic_grid(rows=rows, cols=cols, seed=seed)
    source = 0
    target = rows * cols - 1

    # Cost function: free-flow minutes = length / speed * 60
    cost_fn = free_flow_time_minutes

    # Warm-up run to prime JIT/caches
    _ = dijkstra(graph, source, target, cost_fn)
    _ = astar(graph, source, target, cost_fn, coords)

    # Time Dijkstra over specified runs
    dijkstra_times = []
    dijkstra_result = None
    for _ in range(runs):
        start = time.perf_counter()
        dijkstra_result = dijkstra(graph, source, target, cost_fn)
        elapsed = time.perf_counter() - start
        dijkstra_times.append(elapsed * 1000.0)  # Convert to ms

    # Time A* over specified runs
    astar_times = []
    astar_result = None
    for _ in range(runs):
        start = time.perf_counter()
        astar_result = astar(graph, source, target, cost_fn, coords)
        elapsed = time.perf_counter() - start
        astar_times.append(elapsed * 1000.0)  # Convert to ms

    assert dijkstra_result is not None and astar_result is not None

    dijkstra_cost = dijkstra_result.total_cost
    astar_cost = astar_result.total_cost

    # Optimality verification
    cost_diff = abs(dijkstra_cost - astar_cost)
    assert cost_diff < 1e-6, (
        f"A* optimality check FAILED for {name}: "
        f"Dijkstra={dijkstra_cost:.6f}, A*={astar_cost:.6f}, diff={cost_diff:.6e}"
    )

    dijkstra_mean_ms = sum(dijkstra_times) / len(dijkstra_times)
    astar_mean_ms = sum(astar_times) / len(astar_times)
    speedup = dijkstra_mean_ms / astar_mean_ms if astar_mean_ms > 0 else 1.0

    return {
        "name": name,
        "nodes": rows * cols,
        "edges": graph.edge_count(),
        "dijkstra_cost": dijkstra_cost,
        "astar_cost": astar_cost,
        "cost_diff": cost_diff,
        "dijkstra_mean_ms": dijkstra_mean_ms,
        "astar_mean_ms": astar_mean_ms,
        "speedup": speedup,
        "dijkstra_path_len": len(dijkstra_result.path),
        "astar_path_len": len(astar_result.path),
    }


def main() -> None:
    """Execute synthetic routing benchmarks and display performance comparison."""
    print("========================================================================================")
    print(" AI TrafficOS - Shortest Path Routing Benchmark: Dijkstra vs A*")
    print("========================================================================================")
    print("Config: 5 timed runs per algorithm, corner-to-corner routing (Node 0 -> Last Node)")
    print("Impedance: Free-flow travel time (minutes) = (length_km / speed_kmh) * 60.0")
    print()

    benchmarks = [
        ("1k Grid (32x32)", 32, 32),
        ("10k Grid (100x100)", 100, 100),
    ]

    results = []
    for name, rows, cols in benchmarks:
        print(f"Benchmarking {name} ({rows * cols:,} nodes)...")
        res = benchmark_network(name=name, rows=rows, cols=cols, runs=5, seed=42)
        results.append(res)
        print(
            f"  -> Dijkstra Cost: {res['dijkstra_cost']:.6f} min | "
            f"A* Cost: {res['astar_cost']:.6f} min | "
            f"Diff: {res['cost_diff']:.2e}"
        )
        print("optimality check passed")
        print()

    # Formatted output table
    print("========================================================================================")
    print(" BENCHMARK RESULTS SUMMARY")
    print("========================================================================================")
    header = (
        f"{'Network Topology':<20} | {'Nodes':>6} | {'Edges':>7} | "
        f"{'Algorithm':<9} | {'Mean Time (ms)':>14} | {'Speedup':>9} | {'Cost (min)':>10}"
    )
    print(header)
    print("-" * len(header))

    for res in results:
        d_line = (
            f"{res['name']:<20} | {res['nodes']:>6,} | {res['edges']:>7,} | "
            f"{'Dijkstra':<9} | {res['dijkstra_mean_ms']:>14.3f} | {'baseline':>9} | "
            f"{res['dijkstra_cost']:>10.3f}"
        )
        a_line = (
            f"{res['name']:<20} | {res['nodes']:>6,} | {res['edges']:>7,} | "
            f"{'A*':<9} | {res['astar_mean_ms']:>14.3f} | {res['speedup']:>8.2f}x | "
            f"{res['astar_cost']:>10.3f}"
        )
        print(d_line)
        print(a_line)
        print("-" * len(header))

    print("========================================================================================")
    print("All optimality checks passed successfully.")


if __name__ == "__main__":
    main()
