"""Routing, emergency corridor, dispatch, and telemetry management API router."""

from datetime import datetime, timezone
import heapq
import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.api.v1.auth import get_client_ip
from app.core.audit import log_audit
from app.core.database import get_db
from app.models.auth import User
from app.models.road import Lane, Road
from app.models.traffic import TrafficRecord
from app.schemas.routing import (
    CongestionRankingItem,
    DispatchNextResponse,
    GraphStatsResponse,
    GreenCorridorRequest,
    GreenCorridorResponse,
    RouteEdgeResponse,
    RouteRequest,
    RouteResponse,
    SignalActionResponse,
    TelemetryFlushResponse,
    TelemetryIngestItem,
    TelemetryIngestResponse,
)
from app.services.routing import (
    CostProfile,
    Edge,
    NetworkRegistry,
    NoPathError,
    astar,
    build_dispatch_queue,
    build_graph,
    dijkstra,
    dispatch_next,
    edge_cost,
    get_ingest_buffer,
    plan_green_corridor,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/routing",
    tags=["routing"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "/optimal-route",
    response_model=RouteResponse,
    status_code=status.HTTP_200_OK,
    summary="Calculate optimal route between intersections",
)
async def calculate_optimal_route(
    payload: RouteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RouteResponse:
    """Calculate minimum impedance route using Dijkstra or A* algorithm."""
    graph, road_congestion, node_coords, _ = await build_graph(db)

    profile = CostProfile(
        time_weight=payload.time_weight,
        distance_weight=payload.distance_weight,
        congestion_weight=payload.congestion_weight,
        condition_weight=payload.condition_weight,
    )

    def cost_fn(edge: Edge) -> float:
        c = road_congestion.get(edge.road_id, 0.0)
        return edge_cost(edge, c, profile)

    try:
        if payload.algorithm == "astar":
            result = astar(
                graph=graph,
                source=payload.from_intersection_id,
                target=payload.to_intersection_id,
                cost_fn=cost_fn,
                coords=node_coords,
            )
        else:
            result = dijkstra(
                graph=graph,
                source=payload.from_intersection_id,
                target=payload.to_intersection_id,
                cost_fn=cost_fn,
            )
    except (NoPathError, ValueError) as exc:
        logger.warning(
            "Optimal route failed (%s): %d -> %d: %s",
            payload.algorithm,
            payload.from_intersection_id,
            payload.to_intersection_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    logger.info(
        "Optimal route calculated (%s): %d -> %d, cost=%.2f minutes",
        payload.algorithm,
        payload.from_intersection_id,
        payload.to_intersection_id,
        result.total_cost,
    )

    edge_responses: list[RouteEdgeResponse] = [
        RouteEdgeResponse(
            road_id=edge.road_id,
            from_intersection_id=edge.from_id,
            to_intersection_id=edge.to_id,
            length_km=round(edge.length_km, 3),
            cost_minutes=round(cost_fn(edge), 3),
        )
        for edge in result.edges
    ]

    total_distance = sum(edge.length_km for edge in result.edges)

    return RouteResponse(
        algorithm=result.algorithm,
        path=result.path,
        edges=edge_responses,
        total_cost_minutes=round(result.total_cost, 3),
        total_distance_km=round(total_distance, 3),
    )


@router.post(
    "/green-corridor",
    response_model=GreenCorridorResponse,
    status_code=status.HTTP_200_OK,
    summary="Plan coordinated emergency green wave corridor",
)
async def plan_emergency_corridor(
    payload: GreenCorridorRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> GreenCorridorResponse:
    """Plan emergency green corridor and signal preemption actions along the transit path."""
    graph, road_congestion, node_coords, _ = await build_graph(db)

    try:
        plan = await plan_green_corridor(
            session=db,
            graph=graph,
            road_congestion=road_congestion,
            node_coords=node_coords,
            from_intersection_id=payload.from_intersection_id,
            to_intersection_id=payload.to_intersection_id,
            emergency_speed_kmh=payload.emergency_speed_kmh,
        )
    except (NoPathError, ValueError) as exc:
        logger.warning(
            "Green corridor planning failed: %d -> %d: %s",
            payload.from_intersection_id,
            payload.to_intersection_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="routing.green_corridor_planned",
        actor_user_id=current_user.id,
        entity_type="green_corridor",
        entity_id=None,
        details={
            "corridor_id": plan.corridor_id,
            "from_intersection_id": plan.from_intersection_id,
            "to_intersection_id": plan.to_intersection_id,
            "actor": current_user.email,
            "emergency_speed_kmh": payload.emergency_speed_kmh,
            "estimated_minutes": plan.estimated_minutes,
        },
        ip_address=client_ip,
    )
    await db.commit()

    logger.info(
        "Green corridor planned: corridor_id=%s, %d -> %d by user %s",
        plan.corridor_id,
        plan.from_intersection_id,
        plan.to_intersection_id,
        current_user.email,
    )

    return GreenCorridorResponse(
        corridor_id=plan.corridor_id,
        path=plan.path,
        signal_actions=[
            SignalActionResponse(
                intersection_id=sa.intersection_id,
                signal_id=sa.signal_id,
                action=sa.action,
                duration_seconds=sa.duration_seconds,
                reason=sa.reason,
            )
            for sa in plan.signal_actions
        ],
        estimated_minutes=round(plan.estimated_minutes, 3),
        from_intersection_id=plan.from_intersection_id,
        to_intersection_id=plan.to_intersection_id,
    )


@router.get(
    "/congestion-ranking",
    response_model=list[CongestionRankingItem],
    status_code=status.HTTP_200_OK,
    summary="Rank road corridors by real-time congestion level",
)
async def get_congestion_ranking(
    limit: int = Query(10, ge=1, le=100, description="Maximum number of congested roads to return (1-100)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[CongestionRankingItem]:
    """Retrieve top-k congested roadway corridors across the network."""
    _, road_congestion, _, _ = await build_graph(db)

    if not road_congestion:
        return []

    top_roads = heapq.nlargest(limit, road_congestion.items(), key=lambda item: item[1])
    top_road_ids = [road_id for road_id, _ in top_roads]

    stmt = select(Road).where(Road.id.in_(top_road_ids))
    res = await db.execute(stmt)
    roads_by_id = {r.id: r for r in res.scalars().all()}

    items: list[CongestionRankingItem] = []
    for rank, (road_id, cong_val) in enumerate(top_roads, start=1):
        road = roads_by_id.get(road_id)
        if not road:
            continue
        items.append(
            CongestionRankingItem(
                road_id=road.id,
                road_name=road.name,
                from_intersection_id=road.from_intersection_id,
                to_intersection_id=road.to_intersection_id,
                congestion_level=round(cong_val, 2),
                rank=rank,
            )
        )

    return items


@router.post(
    "/dispatch/next",
    response_model=DispatchNextResponse,
    status_code=status.HTTP_200_OK,
    summary="Dispatch highest priority pending incident or emergency event",
)
async def dispatch_next_operational_item(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> DispatchNextResponse:
    """Triage and dispatch the highest-priority operational incident or emergency transit."""
    queue = await build_dispatch_queue(db)
    item = await dispatch_next(db, queue, current_user)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no pending items",
        )

    new_status = "acknowledged" if item.kind == "incident" else "dispatched"
    message = f"Successfully dispatched {item.kind} #{item.ref_id} with status '{new_status}'"

    return DispatchNextResponse(
        kind=item.kind,
        ref_id=item.ref_id,
        severity=item.severity,
        label=item.label,
        new_status=new_status,
        message=message,
    )


@router.post(
    "/telemetry/ingest",
    response_model=TelemetryIngestResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest batch of lane telemetry sensor observations into staging buffer",
)
async def ingest_telemetry(
    payload: list[TelemetryIngestItem] = Body(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> TelemetryIngestResponse:
    """Stage real-time perception/telemetry items into in-memory bounded ring buffer."""
    if len(payload) > 500:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Batch size exceeds maximum limit of 500 items (received {len(payload)})",
        )

    if not payload:
        return TelemetryIngestResponse(staged=0, dropped=0)

    lane_ids = {item.lane_id for item in payload}
    stmt = select(Lane.id).where(Lane.id.in_(lane_ids))
    res = await db.execute(stmt)
    existing_lane_ids = set(res.scalars().all())
    unknown_lane_ids = sorted(list(lane_ids - existing_lane_ids))

    if unknown_lane_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown lane IDs: {unknown_lane_ids}",
        )

    buffer = get_ingest_buffer()
    now = datetime.now(timezone.utc)
    staged = 0
    dropped = 0

    for item in payload:
        staged_dict = {
            "lane_id": item.lane_id,
            "congestion_level": item.congestion_level,
            "vehicle_count": item.vehicle_count,
            "avg_speed_kmh": item.avg_speed_kmh,
            "recorded_at": now,
        }
        added = buffer.append(staged_dict)
        staged += 1
        if not added:
            dropped += 1

    return TelemetryIngestResponse(staged=staged, dropped=dropped)


@router.post(
    "/telemetry/flush",
    response_model=TelemetryFlushResponse,
    status_code=status.HTTP_200_OK,
    summary="Flush staged telemetry buffer and persist to traffic records database",
)
async def flush_telemetry(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles("admin", "traffic_officer")),
) -> TelemetryFlushResponse:
    """Drain up to 1000 items from telemetry buffer and bulk persist TrafficRecord rows."""
    buffer = get_ingest_buffer()
    items = buffer.drain(1000)

    if not items:
        return TelemetryFlushResponse(staged=0, persisted=0, dropped=0)

    staged_count = len(items)
    lane_ids = {item["lane_id"] for item in items if "lane_id" in item}

    # One batched query mapping lane_id to intersection_id (falling back to road endpoints if necessary)
    lane_stmt = (
        select(Lane.id, Lane.intersection_id, Road.from_intersection_id, Road.to_intersection_id)
        .outerjoin(Road, Lane.road_id == Road.id)
        .where(Lane.id.in_(lane_ids))
    )
    lane_res = await db.execute(lane_stmt)
    lane_to_intersection: dict[int, int] = {}
    for lid, inter_id, from_id, to_id in lane_res.all():
        resolved_inter_id = inter_id if inter_id is not None else (from_id if from_id is not None else to_id)
        if resolved_inter_id is not None:
            lane_to_intersection[lid] = resolved_inter_id

    records_to_insert: list[dict] = []
    dropped_count = 0
    now = datetime.now(timezone.utc)

    for item in items:
        lid = item.get("lane_id")
        inter_id = lane_to_intersection.get(lid)
        if inter_id is None:
            dropped_count += 1
            continue

        raw_cong = item.get("congestion_level", 0.0)
        cong_int = int(round(raw_cong)) if isinstance(raw_cong, (int, float)) else 0

        records_to_insert.append(
            {
                "intersection_id": inter_id,
                "lane_id": lid,
                "recorded_at": item.get("recorded_at") or now,
                "vehicle_count": item.get("vehicle_count", 0),
                "avg_speed_kmh": item.get("avg_speed_kmh"),
                "congestion_level": cong_int,
                "source": "sensor",
            }
        )

    if records_to_insert:
        insert_stmt = insert(TrafficRecord).values(records_to_insert)
        await db.execute(insert_stmt)

    client_ip = get_client_ip(request)
    await log_audit(
        db=db,
        action="telemetry.flushed",
        actor_user_id=current_user.id,
        entity_type="traffic_record",
        entity_id=None,
        details={
            "staged": staged_count,
            "persisted": len(records_to_insert),
            "dropped": dropped_count,
        },
        ip_address=client_ip,
    )
    await db.commit()

    return TelemetryFlushResponse(
        staged=staged_count,
        persisted=len(records_to_insert),
        dropped=dropped_count,
    )


@router.get(
    "/graph-stats",
    response_model=GraphStatsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get topology node and edge counts for road network graph",
)
async def get_graph_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GraphStatsResponse:
    """Return intersection count, road count, and directed edge count from graph builder."""
    graph, road_congestion, _, _ = await build_graph(db)
    return GraphStatsResponse(
        intersection_count=len(graph.adjacency),
        road_count=len(road_congestion),
        directed_edge_count=graph.edge_count(),
    )
