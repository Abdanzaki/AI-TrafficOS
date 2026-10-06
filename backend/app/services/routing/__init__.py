"""Routing and road network graph package.

Exports public data structures, cost functions, graph builders, shortest-path algorithms,
green-corridor coordination, dispatch queues, telemetry buffers, and network registries
for Phase 3 traffic algorithms and dynamic network routing.
"""

from app.services.routing.builders import build_graph
from app.services.routing.costs import (
    CostProfile,
    condition_factor,
    congestion_factor,
    edge_cost,
    free_flow_time_minutes,
)
from app.services.routing.dispatch import (
    DispatchItem,
    DispatchQueue,
    build_dispatch_queue,
    dispatch_next,
)
from app.services.routing.graph import Edge, RoadGraph
from app.services.routing.green_corridor import (
    CorridorSignalAction,
    GreenCorridorPlan,
    plan_green_corridor,
)
from app.services.routing.paths import (
    NoPathError,
    RouteResult,
    astar,
    dijkstra,
    haversine_km,
)
from app.services.routing.queues import (
    EventBuffer,
    SlidingWindow,
    get_ingest_buffer,
)
from app.services.routing.registries import NetworkRegistry

__all__ = [
    # Graph & Topology
    "Edge",
    "RoadGraph",
    # Cost & Impedance
    "CostProfile",
    "free_flow_time_minutes",
    "congestion_factor",
    "condition_factor",
    "edge_cost",
    "build_graph",
    # Shortest Path Algorithms
    "RouteResult",
    "NoPathError",
    "dijkstra",
    "astar",
    "haversine_km",
    # Emergency Green Corridor Planning
    "GreenCorridorPlan",
    "CorridorSignalAction",
    "plan_green_corridor",
    # Priority Dispatch
    "DispatchQueue",
    "DispatchItem",
    "build_dispatch_queue",
    "dispatch_next",
    # Telemetry Ingest & Buffering
    "EventBuffer",
    "SlidingWindow",
    "get_ingest_buffer",
    # Network Registry
    "NetworkRegistry",
]
