"""Integration tests for Phase 3 routing, dispatch, and telemetry APIs.

Uses real PostgreSQL database session and ASGI HTTP client fixtures:
- Diamond network seeding (4 junctions A, B, C, D; roads A-B, A-C, B-D, C-D; signal + phases at B; lane).
- build_graph topology verification, default 0.0 congestion.
- POST /api/v1/routing/optimal-route: analyst 200, valid path A->D, positive total cost, distance matches edge lengths.
- Optimal-route edge cases: unknown intersection ID returns 404, algorithm='dijkstra' returns identical route.
- POST /api/v1/routing/green-corridor: traffic_officer 200 with corridor signal actions, analyst 403.
- GET /api/v1/routing/congestion-ranking and GET /api/v1/routing/graph-stats responses.
- Priority dispatch lifecycle flow: critical incident + emergency event via Phase 2 APIs;
  POST /api/v1/routing/dispatch/next returns critical incident first (status becomes 'acknowledged' in DB);
  second call returns emergency event; analyst returns 403; empty queue returns 404.
- Telemetry ingest & flush: invalid lane_id 422, valid lane stages items, flush persists TrafficRecord rows in DB, buffer empty.
- NetworkRegistry: O(1) lookups by ID and municipal code.
"""

import uuid
from httpx import AsyncClient
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import engine
from app.models.event import Incident
from app.models.intersection import Intersection
from app.models.road import Lane, Road
from app.models.signal import Signal, SignalPhase
from app.models.traffic import TrafficRecord
from app.services.routing import NetworkRegistry, build_graph, get_ingest_buffer


@pytest.fixture(autouse=True)
async def cleanup_db_resources():
    """Ensure all SQLAlchemy connection pool resources are cleanly closed per test."""
    yield
    await engine.dispose()


@pytest.fixture
async def diamond_network(db_session: AsyncSession) -> dict:
    """Fixture that seeds a 4-intersection diamond network in PostgreSQL.

    Topology:
            B (Signal)
           / \
          A   D
           \ /
            C
    """
    uid = uuid.uuid4().hex[:8]

    # 1. Four intersections
    node_a = Intersection(
        name="Diamond Node A",
        code=f"DIA_A_{uid}",
        status="active",
        city="TrafficCity",
        lat=37.770,
        lon=-122.420,
    )
    node_b = Intersection(
        name="Diamond Node B",
        code=f"DIA_B_{uid}",
        status="active",
        city="TrafficCity",
        lat=37.775,
        lon=-122.415,
    )
    node_c = Intersection(
        name="Diamond Node C",
        code=f"DIA_C_{uid}",
        status="active",
        city="TrafficCity",
        lat=37.765,
        lon=-122.415,
    )
    node_d = Intersection(
        name="Diamond Node D",
        code=f"DIA_D_{uid}",
        status="active",
        city="TrafficCity",
        lat=37.770,
        lon=-122.410,
    )
    db_session.add_all([node_a, node_b, node_c, node_d])
    await db_session.flush()

    # 2. Roads forming diamond: A-B, A-C, B-D, C-D (bidirectional)
    # A->B->D = 1.0 + 1.2 = 2.2 km (arterial, 50 km/h)
    # A->C->D = 1.5 + 1.8 = 3.3 km (collector, 40 km/h)
    road_ab = Road(
        name="Arterial A-B",
        road_type="arterial",
        speed_limit_kmh=50,
        from_intersection_id=node_a.id,
        to_intersection_id=node_b.id,
        length_km=1.0,
        is_bidirectional=True,
    )
    road_ac = Road(
        name="Collector A-C",
        road_type="collector",
        speed_limit_kmh=40,
        from_intersection_id=node_a.id,
        to_intersection_id=node_c.id,
        length_km=1.5,
        is_bidirectional=True,
    )
    road_bd = Road(
        name="Arterial B-D",
        road_type="arterial",
        speed_limit_kmh=50,
        from_intersection_id=node_b.id,
        to_intersection_id=node_d.id,
        length_km=1.2,
        is_bidirectional=True,
    )
    road_cd = Road(
        name="Collector C-D",
        road_type="collector",
        speed_limit_kmh=40,
        from_intersection_id=node_c.id,
        to_intersection_id=node_d.id,
        length_km=1.8,
        is_bidirectional=True,
    )
    db_session.add_all([road_ab, road_ac, road_bd, road_cd])
    await db_session.flush()

    # 3. Traffic Signal with 2 phases at Intersection B
    signal_b = Signal(
        intersection_id=node_b.id,
        code=f"SIG_B_{uid}",
        status="active",
    )
    db_session.add(signal_b)
    await db_session.flush()

    phase_1 = SignalPhase(
        signal_id=signal_b.id,
        intersection_id=node_b.id,
        name="North-South Phase",
        phase_order=1,
        duration_seconds=45,
        state="green",
        is_active=True,
    )
    phase_2 = SignalPhase(
        signal_id=signal_b.id,
        intersection_id=node_b.id,
        name="East-West Phase",
        phase_order=2,
        duration_seconds=30,
        state="red",
        is_active=True,
    )
    db_session.add_all([phase_1, phase_2])

    # 4. Lane on road A-B entering intersection B
    lane = Lane(
        road_id=road_ab.id,
        intersection_id=node_b.id,
        lane_number=1,
        direction="northbound",
        lane_type="through",
    )
    db_session.add(lane)
    await db_session.commit()

    return {
        "nodes": {"A": node_a, "B": node_b, "C": node_c, "D": node_d},
        "roads": {"AB": road_ab, "AC": road_ac, "BD": road_bd, "CD": road_cd},
        "signal": signal_b,
        "phases": [phase_1, phase_2],
        "lane": lane,
    }


# ==============================================================================
# 1. build_graph Topological Construction
# ==============================================================================

@pytest.mark.anyio
async def test_build_graph_topology_and_defaults(
    db_session: AsyncSession,
    diamond_network: dict,
):
    """Verify build_graph hydrates the diamond network with correct node/edge counts and 0.0 default congestion."""
    graph, road_congestion, node_coords, code_to_id = await build_graph(db_session)

    nodes = diamond_network["nodes"]
    roads = diamond_network["roads"]

    # All 4 nodes are in graph
    for key, node in nodes.items():
        assert node.id in graph.adjacency
        assert node.id in node_coords
        assert node_coords[node.id] == (node.lat, node.lon)
        assert code_to_id[node.code] == node.id

    # 4 bidirectional roads = 8 directed edges for this diamond
    for r in roads.values():
        fwd = graph.get_edge(r.from_intersection_id, r.to_intersection_id)
        rev = graph.get_edge(r.to_intersection_id, r.from_intersection_id)
        assert fwd is not None
        assert rev is not None
        assert fwd.length_km == r.length_km
        # Default road congestion is 0.0 (uncongested free flow)
        assert road_congestion[r.id] == 0.0


# ==============================================================================
# 2. Optimal Route Calculation (Analyst, 404, Dijkstra comparison)
# ==============================================================================

@pytest.mark.anyio
async def test_optimal_route_endpoint(
    async_client: AsyncClient,
    test_users: dict,
    diamond_network: dict,
):
    """Verify POST /optimal-route works for analyst, validates costs/distance, and handles errors."""
    analyst_headers = {"Authorization": f"Bearer {test_users['analyst']['token']}"}
    node_a = diamond_network["nodes"]["A"]
    node_d = diamond_network["nodes"]["D"]

    # 1. Analyst requests optimal route from A to D via A*
    resp = await async_client.post(
        "/api/v1/routing/optimal-route",
        headers=analyst_headers,
        json={
            "from_intersection_id": node_a.id,
            "to_intersection_id": node_d.id,
            "algorithm": "astar",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["algorithm"] == "astar"
    assert data["path"][0] == node_a.id
    assert data["path"][-1] == node_d.id
    assert data["total_cost_minutes"] > 0
    # The A-B-D path is 1.0 + 1.2 = 2.2 km, shorter than A-C-D (3.3 km)
    assert data["total_distance_km"] == pytest.approx(2.2, rel=1e-3)
    assert len(data["edges"]) == len(data["path"]) - 1

    # 2. Algorithm dijkstra returns identical route and cost
    dijkstra_resp = await async_client.post(
        "/api/v1/routing/optimal-route",
        headers=analyst_headers,
        json={
            "from_intersection_id": node_a.id,
            "to_intersection_id": node_d.id,
            "algorithm": "dijkstra",
        },
    )
    assert dijkstra_resp.status_code == 200
    d_data = dijkstra_resp.json()
    assert d_data["algorithm"] == "dijkstra"
    assert d_data["path"] == data["path"]
    assert d_data["total_cost_minutes"] == pytest.approx(data["total_cost_minutes"], rel=1e-3)

    # 3. Unknown intersection ID returns 404
    missing_resp = await async_client.post(
        "/api/v1/routing/optimal-route",
        headers=analyst_headers,
        json={
            "from_intersection_id": 999999,
            "to_intersection_id": node_d.id,
            "algorithm": "astar",
        },
    )
    assert missing_resp.status_code == 404


# ==============================================================================
# 3. Green Corridor Planning and RBAC
# ==============================================================================

@pytest.mark.anyio
async def test_green_corridor_endpoint_and_rbac(
    async_client: AsyncClient,
    test_users: dict,
    diamond_network: dict,
):
    """Verify POST /green-corridor requires officer/admin and includes signal actions."""
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    analyst_headers = {"Authorization": f"Bearer {test_users['analyst']['token']}"}
    node_a = diamond_network["nodes"]["A"]
    node_d = diamond_network["nodes"]["D"]
    node_b = diamond_network["nodes"]["B"]

    # 1. Analyst forbidden (403)
    forbidden_resp = await async_client.post(
        "/api/v1/routing/green-corridor",
        headers=analyst_headers,
        json={
            "from_intersection_id": node_a.id,
            "to_intersection_id": node_d.id,
            "emergency_speed_kmh": 60.0,
        },
    )
    assert forbidden_resp.status_code == 403

    # 2. Traffic officer succeeds (200)
    ok_resp = await async_client.post(
        "/api/v1/routing/green-corridor",
        headers=officer_headers,
        json={
            "from_intersection_id": node_a.id,
            "to_intersection_id": node_d.id,
            "emergency_speed_kmh": 60.0,
        },
    )
    assert ok_resp.status_code == 200, ok_resp.text
    plan = ok_resp.json()

    assert plan["from_intersection_id"] == node_a.id
    assert plan["to_intersection_id"] == node_d.id
    assert plan["estimated_minutes"] > 0
    assert len(plan["signal_actions"]) == len(plan["path"])

    # Signal actions must cover path junctions; node B has active signal
    actions_by_node = {sa["intersection_id"]: sa for sa in plan["signal_actions"]}
    assert node_a.id in actions_by_node
    assert node_d.id in actions_by_node
    if node_b.id in actions_by_node:
        action_b = actions_by_node[node_b.id]
        assert action_b["signal_id"] == diamond_network["signal"].id
        assert action_b["action"] == "extend_green"


# ==============================================================================
# 4. Congestion Ranking & Graph Stats Endpoints
# ==============================================================================

@pytest.mark.anyio
async def test_congestion_ranking_and_graph_stats(
    async_client: AsyncClient,
    test_users: dict,
    diamond_network: dict,
):
    """Verify GET /congestion-ranking and GET /graph-stats return expected structures."""
    analyst_headers = {"Authorization": f"Bearer {test_users['analyst']['token']}"}

    # 1. Congestion ranking
    rank_resp = await async_client.get(
        "/api/v1/routing/congestion-ranking?limit=10",
        headers=analyst_headers,
    )
    assert rank_resp.status_code == 200
    ranking = rank_resp.json()
    assert isinstance(ranking, list)
    if ranking:
        assert "road_id" in ranking[0]
        assert "congestion_level" in ranking[0]
        assert "rank" in ranking[0]

    # 2. Graph stats
    stats_resp = await async_client.get(
        "/api/v1/routing/graph-stats",
        headers=analyst_headers,
    )
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    assert stats["intersection_count"] >= 4
    assert stats["road_count"] >= 4
    assert stats["directed_edge_count"] >= 8


# ==============================================================================
# 5. Priority Dispatch Lifecycle Flow
# ==============================================================================

@pytest.mark.anyio
async def test_dispatch_flow_incident_and_emergency(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_users: dict,
    diamond_network: dict,
):
    """Verify dispatch triage pops critical incident first (updating status to acknowledged),

    then emergency event, enforces RBAC, and returns 404 when queue is drained.
    """
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    analyst_headers = {"Authorization": f"Bearer {test_users['analyst']['token']}"}
    node_b = diamond_network["nodes"]["B"]

    # Drain any pre-existing pending incidents/emergencies from earlier tests
    while True:
        drain_check = await async_client.post("/api/v1/routing/dispatch/next", headers=officer_headers)
        if drain_check.status_code != 200:
            break

    # 1. Create a critical incident via Phase 2 endpoint
    inc_resp = await async_client.post(
        "/api/v1/incidents",
        headers=officer_headers,
        json={
            "intersection_id": node_b.id,
            "severity": "critical",
            "status": "reported",
            "description": "Hazardous spill at Junction B",
        },
    )
    assert inc_resp.status_code == 201
    created_incident_id = inc_resp.json()["id"]

    # 2. Create an emergency event via Phase 2 endpoint (priority 2 -> high severity)
    em_resp = await async_client.post(
        "/api/v1/emergency-events",
        headers=officer_headers,
        json={
            "intersection_id": node_b.id,
            "vehicle_type": "ambulance",
            "priority": 2,
            "status": "active",
        },
    )
    assert em_resp.status_code == 201
    created_emergency_id = em_resp.json()["id"]

    # 3. Analyst forbidden from dispatching (403)
    analyst_forbidden = await async_client.post(
        "/api/v1/routing/dispatch/next",
        headers=analyst_headers,
    )
    assert analyst_forbidden.status_code == 403

    # 4. Officer dispatches next item: Critical incident must be returned FIRST!
    first_dispatch = await async_client.post(
        "/api/v1/routing/dispatch/next",
        headers=officer_headers,
    )
    assert first_dispatch.status_code == 200
    first_item = first_dispatch.json()
    assert first_item["kind"] == "incident"
    assert first_item["ref_id"] == created_incident_id
    assert first_item["severity"] == "critical"
    assert first_item["new_status"] == "acknowledged"

    # Verify incident status became 'acknowledged' in the database
    async with db_session.begin():
        inc_in_db = (
            await db_session.execute(select(Incident).where(Incident.id == created_incident_id))
        ).scalar_one_or_none()
        assert inc_in_db is not None
        assert inc_in_db.status == "acknowledged"

    # 5. Second dispatch returns the emergency event!
    second_dispatch = await async_client.post(
        "/api/v1/routing/dispatch/next",
        headers=officer_headers,
    )
    assert second_dispatch.status_code == 200
    second_item = second_dispatch.json()
    assert second_item["kind"] == "emergency"
    assert second_item["ref_id"] == created_emergency_id
    assert second_item["new_status"] == "dispatched"

    # 6. Third dispatch on empty queue returns 404
    empty_dispatch = await async_client.post(
        "/api/v1/routing/dispatch/next",
        headers=officer_headers,
    )
    assert empty_dispatch.status_code == 404


# ==============================================================================
# 6. Telemetry Ingestion and Buffer Flush
# ==============================================================================

@pytest.mark.anyio
async def test_telemetry_ingest_and_flush_flow(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_users: dict,
    diamond_network: dict,
):
    """Verify telemetry ingest rejects unknown lanes with 422, stages real lanes,

    and flush persists TrafficRecord rows to DB, draining the buffer.
    """
    officer_headers = {"Authorization": f"Bearer {test_users['officer']['token']}"}
    real_lane_id = diamond_network["lane"].id

    # 1. Unknown lane_id rejected with 422
    invalid_resp = await async_client.post(
        "/api/v1/routing/telemetry/ingest",
        headers=officer_headers,
        json=[
            {
                "lane_id": 999999,
                "congestion_level": 50.0,
                "vehicle_count": 10,
            }
        ],
    )
    assert invalid_resp.status_code == 422

    # 2. Ingest with real lane succeeds (200) and stages item
    ingest_resp = await async_client.post(
        "/api/v1/routing/telemetry/ingest",
        headers=officer_headers,
        json=[
            {
                "lane_id": real_lane_id,
                "congestion_level": 75.0,
                "vehicle_count": 18,
                "avg_speed_kmh": 38.5,
            },
            {
                "lane_id": real_lane_id,
                "congestion_level": 80.0,
                "vehicle_count": 22,
                "avg_speed_kmh": 32.0,
            },
        ],
    )
    assert ingest_resp.status_code == 200
    assert ingest_resp.json()["staged"] == 2
    assert ingest_resp.json()["dropped"] == 0

    # 3. Flush persists TrafficRecord rows
    count_before = (
        await db_session.execute(
            select(func.count()).select_from(TrafficRecord).where(TrafficRecord.lane_id == real_lane_id)
        )
    ).scalar_one()

    flush_resp = await async_client.post(
        "/api/v1/routing/telemetry/flush",
        headers=officer_headers,
    )
    assert flush_resp.status_code == 200
    flush_data = flush_resp.json()
    assert flush_data["staged"] >= 2
    assert flush_data["persisted"] >= 2

    # Verify rows persisted in DB
    count_after = (
        await db_session.execute(
            select(func.count()).select_from(TrafficRecord).where(TrafficRecord.lane_id == real_lane_id)
        )
    ).scalar_one()
    assert count_after >= count_before + 2

    # Buffer must be empty after flush
    buf = get_ingest_buffer()
    assert len(buf) == 0


# ==============================================================================
# 7. NetworkRegistry O(1) Lookups
# ==============================================================================

@pytest.mark.anyio
async def test_network_registry_lookups(
    db_session: AsyncSession,
    diamond_network: dict,
):
    """Verify NetworkRegistry builds in 3 queries and provides O(1) lookups by ID and municipal code."""
    registry = await NetworkRegistry.build(db_session)

    node_a = diamond_network["nodes"]["A"]
    node_b = diamond_network["nodes"]["B"]
    signal_b = diamond_network["signal"]

    # 1. Lookup junction by ID
    j_a = registry.get_junction(node_a.id)
    assert j_a is not None
    assert j_a.id == node_a.id
    assert j_a.code == node_a.code

    # 2. Lookup junction ID by municipal code
    assert registry.get_junction_by_code(node_a.code) == node_a.id
    assert registry.get_junction_by_code(node_b.code) == node_b.id
    assert registry.get_junction_by_code("NON_EXISTENT_CODE") is None

    # 3. Signals for intersection B
    b_signals = registry.signals_for(node_b.id)
    assert len(b_signals) >= 1
    assert any(s.id == signal_b.id for s in b_signals)

    # 4. Phases for signal B
    phases = registry.phases_for(signal_b.id)
    assert len(phases) == 2
    assert {p.phase_order for p in phases} == {1, 2}
