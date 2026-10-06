"""Graph construction and real-time state hydration services.

Builds in-memory road network topology from database entities and calculates
empirical corridor congestion levels from recent traffic sensor records using
efficient batched queries.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intersection import Intersection
from app.models.road import Lane, Road
from app.models.traffic import TrafficRecord
from app.services.routing.graph import Edge, RoadGraph


async def build_graph(
    session: AsyncSession,
) -> tuple[RoadGraph, dict[int, float], dict[int, tuple[float, float]], dict[str, int]]:
    """Construct an in-memory road network graph and hydrate current corridor congestion.

    Queries:
        1. All registered intersections to instantiate graph nodes, coordinate
           lookups, and municipal code mappings.
        2. All roadway corridors with defined from/to junction endpoints to construct
           directed graph arcs (expanding bidirectional roads into opposing pairs).
        3. Batched traffic records within the trailing 60-minute window across all lanes
           belonging to loaded roads, computing mean congestion percentages per road (0.0 if none).

    Performance:
        Executes exactly three indexed queries with zero N+1 overhead, aggregating lane-level
        traffic metrics into corridor-level congestion directly inside the database engine.

    Returns:
        tuple containing:
            - RoadGraph: Hydrated directed network graph.
            - dict[int, float]: Mapping of road_id -> average congestion level [0.0, 100.0].
            - dict[int, tuple[float, float]]: Mapping of intersection_id -> (lat, lon).
            - dict[str, int]: Mapping of municipal intersection code -> intersection_id.
    """
    # 1. Fetch all intersections
    inter_stmt = select(
        Intersection.id,
        Intersection.code,
        Intersection.lat,
        Intersection.lon,
    )
    inter_result = await session.execute(inter_stmt)
    inter_rows = inter_result.all()

    graph = RoadGraph()
    node_coords: dict[int, tuple[float, float]] = {}
    code_to_id: dict[str, int] = {}

    for inter_id, code, lat, lon in inter_rows:
        graph.add_node(inter_id)
        if lat is not None and lon is not None:
            node_coords[inter_id] = (float(lat), float(lon))
        if code:
            code_to_id[code] = inter_id

    # 2. Fetch all roads with complete junction endpoint pairs
    road_stmt = select(Road).where(
        Road.from_intersection_id.is_not(None),
        Road.to_intersection_id.is_not(None),
    )
    road_result = await session.execute(road_stmt)
    roads = road_result.scalars().all()

    road_ids: list[int] = []
    road_congestion: dict[int, float] = {}

    for road in roads:
        road_ids.append(road.id)
        # Default baseline congestion is 0.0 (uncongested / free-flow)
        road_congestion[road.id] = 0.0

        length = float(road.length_km) if road.length_km is not None else 1.0
        speed = float(road.speed_limit_kmh) if road.speed_limit_kmh is not None else 50.0

        edge = Edge(
            road_id=road.id,
            from_id=road.from_intersection_id,  # type: ignore[arg-type]
            to_id=road.to_intersection_id,      # type: ignore[arg-type]
            length_km=length,
            speed_limit_kmh=speed,
            road_type=road.road_type or "local",
            capacity_veh_per_hr=road.capacity_veh_per_hr,
            bidirectional=road.is_bidirectional if road.is_bidirectional is not None else True,
        )
        graph.add_edge(edge)

    # 3. Batched computation of per-road average congestion in the trailing 60 minutes
    if road_ids:
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=60)
        congestion_stmt = (
            select(
                Lane.road_id,
                func.avg(TrafficRecord.congestion_level).label("avg_congestion"),
            )
            .join(TrafficRecord, TrafficRecord.lane_id == Lane.id)
            .where(
                Lane.road_id.in_(road_ids),
                TrafficRecord.recorded_at >= cutoff_time,
            )
            .group_by(Lane.road_id)
        )
        congestion_result = await session.execute(congestion_stmt)
        for road_id, avg_congestion in congestion_result.all():
            if avg_congestion is not None:
                road_congestion[road_id] = float(avg_congestion)

    return graph, road_congestion, node_coords, code_to_id
