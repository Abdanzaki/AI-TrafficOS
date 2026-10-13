"""Comprehensive tests for Citizen Assistant module and citizen role RBAC (Batch 3 Brief C).

Covers:
1. Strict citizen / control-room data separation invariant:
   - Enumerates citizen tools and asserts none are in the control-room-only set.
   - Verifies runtime validation rejects control-room tools with PermissionDeniedError.
2. Direct tool invocation role permission tests:
   - Citizen caller role CANNOT access any control-room tools even if invoked directly.
   - Citizen CAN access public citizen tools directly.
3. Grounded public traffic conditions answering:
   - Citizen asking traffic conditions -> 200 OK with grounded answer, tools_used, and provenance='observed'.
4. Out-of-scope graceful refusal tests:
   - Asking for signal timing plans -> 200 OK with refused=True and refusal message.
   - Asking for emergency events -> 200 OK with refused=True.
   - Asking for control decisions -> 200 OK with refused=True.
5. In-scope public incident notices, how-to-report, and general help:
   - Verified grounded answers without data fabrication.
6. API endpoint RBAC enforcement:
   - Citizen CANNOT access /api/v1/assistant/chat (403 Forbidden).
   - Citizen CAN access /api/v1/citizen/chat (200 OK).
   - Unauthenticated request to /api/v1/citizen/chat is rejected with 401 Unauthorized.
7. Audit log verification:
   - Querying /api/v1/citizen/chat creates immutable audit log with action='citizen.chat'.
"""

from httpx import AsyncClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.citizen import (
    CITIZEN_TOOL_ALLOWLIST,
    CONTROL_ROOM_ONLY_TOOLS,
    CitizenNLU,
    CitizenProvider,
    get_citizen_general_help,
    get_how_to_report,
    get_public_incident_notices,
    get_public_traffic_conditions,
    validate_citizen_tool,
)
from app.assistant.errors import PermissionDeniedError
from app.assistant.tools import (
    get_analytics_summary,
    get_congestion_ranking,
    get_control_decisions,
    get_emergency_events,
    get_incidents,
    get_junction_history,
    get_predictions_30min,
    get_routing_advice,
    get_signal_status,
    get_traffic_state,
    simulate_signal_timing,
)
from app.core.database import AsyncSessionLocal, engine
from app.models.audit import AuditLog
from app.models.intersection import Intersection
from app.models.traffic import TrafficRecord


@pytest.fixture(autouse=True)
async def clean_engine_pool():
    """Ensure connection pool is disposed between tests to prevent event loop mismatch."""
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def ensure_test_intersections_and_traffic():
    """Ensure baseline test intersections and sample traffic records exist."""
    async with AsyncSessionLocal() as session:
        for jid in (1, 2, 3):
            existing = await session.get(Intersection, jid)
            if not existing:
                inter = Intersection(
                    id=jid,
                    name=f"Metro Crossing {jid}",
                    code=f"CIT-{jid:03d}",
                    status="active",
                    city="Metropolis",
                    zone="Downtown",
                    lat=37.7749 + (jid * 0.001),
                    lon=-122.4194 + (jid * 0.001),
                )
                session.add(inter)

        # Ensure at least one traffic record exists for junction 1
        stmt = select(TrafficRecord).where(TrafficRecord.intersection_id == 1).limit(1)
        res = await session.execute(stmt)
        record = res.scalars().first()
        if not record:
            tr = TrafficRecord(
                intersection_id=1,
                vehicle_count=42,
                avg_speed_kmh=35.5,
                congestion_level=45.0,
                source="sensor",
            )
            session.add(tr)

        await session.commit()


# ==============================================================================
# 1. STRICT CITIZEN / CONTROL-ROOM DATA SEPARATION & ALLOWLIST INVARIANTS
# ==============================================================================


@pytest.mark.anyio
async def test_strict_toolset_separation_and_disjointness():
    """Enforce that citizen tools and control-room-only tools are strictly disjoint."""
    # 1. Citizen tools set must be completely disjoint from control-room set
    intersection = CITIZEN_TOOL_ALLOWLIST.intersection(CONTROL_ROOM_ONLY_TOOLS)
    assert len(intersection) == 0, f"Violation: tools {intersection} exist in both citizen and control room sets!"
    assert CITIZEN_TOOL_ALLOWLIST.isdisjoint(CONTROL_ROOM_ONLY_TOOLS)

    # 2. Every citizen tool must pass validation
    for tool_name in CITIZEN_TOOL_ALLOWLIST:
        validate_citizen_tool(tool_name)  # should not raise

    # 3. Every control-room tool must be rejected by citizen validator
    for cr_tool in CONTROL_ROOM_ONLY_TOOLS:
        with pytest.raises(PermissionDeniedError) as exc_info:
            validate_citizen_tool(cr_tool)
        assert exc_info.value.role == "citizen"
        assert exc_info.value.domain == cr_tool

    # 4. Unknown tool not in allowlist must be rejected
    with pytest.raises(PermissionDeniedError):
        validate_citizen_tool("unauthorized_random_tool")


# ==============================================================================
# 2. ROLE PERMISSION TESTS: CITIZEN CANNOT ACCESS CONTROL-ROOM TOOLS DIRECTLY
# ==============================================================================


@pytest.mark.anyio
async def test_citizen_cannot_access_control_room_tools_directly():
    """Verify that a caller with caller_role='citizen' is rejected by ALL 11 control-room tools."""
    async with AsyncSessionLocal() as session:
        # 1. get_traffic_state (raw telemetry)
        with pytest.raises(PermissionDeniedError) as exc_info:
            await get_traffic_state(session, caller_role="citizen", junction_id=1)
        assert exc_info.value.role == "citizen"
        assert exc_info.value.domain == "traffic_state"

        # 2. get_signal_status (signal hardware controllers & phases)
        with pytest.raises(PermissionDeniedError) as exc_info:
            await get_signal_status(session, caller_role="citizen", junction_id=1)
        assert exc_info.value.role == "citizen"
        assert exc_info.value.domain == "signal_status"

        # 3. simulate_signal_timing (point-queue macroscopic simulation)
        with pytest.raises(PermissionDeniedError) as exc_info:
            await simulate_signal_timing(session, caller_role="citizen", junction_id=1, green_seconds=45)
        assert exc_info.value.role == "citizen"
        assert exc_info.value.domain == "simulate_signal_timing"

        # 4. get_control_decisions (AI supervisory decisions & rationales)
        with pytest.raises(PermissionDeniedError) as exc_info:
            await get_control_decisions(session, caller_role="citizen", junction_id=1)
        assert exc_info.value.role == "citizen"
        assert exc_info.value.domain == "control_decisions"

        # 5. get_emergency_events (emergency vehicle routes & dispatches)
        with pytest.raises(PermissionDeniedError) as exc_info:
            await get_emergency_events(session, caller_role="citizen", active_only=True)
        assert exc_info.value.role == "citizen"
        assert exc_info.value.domain == "emergency_events"

        # 6. get_predictions_30min (forward AI forecasts)
        with pytest.raises(PermissionDeniedError) as exc_info:
            await get_predictions_30min(session, caller_role="citizen", junction_id=1)
        assert exc_info.value.role == "citizen"
        assert exc_info.value.domain == "predictions_30min"

        # 7. get_routing_advice (operational dynamic dispatch)
        with pytest.raises(PermissionDeniedError) as exc_info:
            await get_routing_advice(session, caller_role="citizen", origin_id=1, destination_id=2)
        assert exc_info.value.role == "citizen"
        assert exc_info.value.domain == "routing_advice"

        # 8. get_congestion_ranking (network internal ranking)
        with pytest.raises(PermissionDeniedError) as exc_info:
            await get_congestion_ranking(session, caller_role="citizen")
        assert exc_info.value.role == "citizen"
        assert exc_info.value.domain == "congestion_ranking"

        # 9. get_incidents (internal safety log)
        with pytest.raises(PermissionDeniedError) as exc_info:
            await get_incidents(session, caller_role="citizen")
        assert exc_info.value.role == "citizen"
        assert exc_info.value.domain == "incidents"

        # 10. get_junction_history (chronological telemetry audit)
        with pytest.raises(PermissionDeniedError) as exc_info:
            await get_junction_history(session, caller_role="citizen", junction_id=1)
        assert exc_info.value.role == "citizen"
        assert exc_info.value.domain == "junction_history"

        # 11. get_analytics_summary (aggregated operations totals)
        with pytest.raises(PermissionDeniedError) as exc_info:
            await get_analytics_summary(session, caller_role="citizen")
        assert exc_info.value.role == "citizen"
        assert exc_info.value.domain == "analytics_summary"


# ==============================================================================
# 3. PUBLIC CITIZEN TOOLS DIRECT TESTS
# ==============================================================================


@pytest.mark.anyio
async def test_public_citizen_tools_return_safe_data():
    """Verify public citizen tools execute properly and return strictly public-safe data."""
    async with AsyncSessionLocal() as session:
        # 1. get_public_traffic_conditions
        traffic = await get_public_traffic_conditions(session, junction_id=1)
        assert traffic["provenance"] == "observed"
        assert "data" in traffic

        # 2. get_public_incident_notices
        incidents = await get_public_incident_notices(session, junction_id=1)
        assert incidents["provenance"] == "observed"

        # 3. get_how_to_report
        guide = get_how_to_report()
        assert guide["provenance"] == "observed"
        assert "guidance" in guide["data"]

        # 4. get_citizen_general_help
        help_info = get_citizen_general_help()
        assert help_info["provenance"] == "observed"
        assert "capabilities" in help_info["data"]


# ==============================================================================
# 4. NLU INTENT EVALUATION & OUT-OF-SCOPE REFUSAL TESTS
# ==============================================================================


@pytest.mark.anyio
async def test_citizen_asking_traffic_conditions_grounded():
    """Verify citizen asking traffic conditions receives grounded answer with provenance."""
    nlu = CitizenNLU()
    async with AsyncSessionLocal() as session:
        res = await nlu.execute(session, message="How is traffic right now?")
        assert res.intent == "traffic_conditions"
        assert res.refused is False
        assert res.provenance == "observed"
        assert "CURRENT" in res.answer or "TRAFFIC" in res.answer
        assert "get_public_traffic_conditions" in res.tools_used


@pytest.mark.anyio
async def test_citizen_asking_signal_timing_plans_refused():
    """Verify citizen asking for signal timing plans is refused gracefully with refused=True."""
    nlu = CitizenNLU()
    async with AsyncSessionLocal() as session:
        queries = [
            "What is the signal timing plan for junction 1?",
            "Can you change the signal timing to green for 60 seconds?",
            "Extend green light at the next intersection",
            "Show me the phase timing and cycle length",
        ]
        for query in queries:
            res = await nlu.execute(session, message=query)
            assert res.refused is True, f"Failed to refuse query: '{query}'"
            assert res.intent == "out_of_scope"
            assert "restricted to municipal control-room" in res.answer
            assert len(res.tools_used) == 0


@pytest.mark.anyio
async def test_citizen_asking_emergency_events_refused():
    """Verify citizen asking for emergency events or transit tracking is refused gracefully."""
    nlu = CitizenNLU()
    async with AsyncSessionLocal() as session:
        queries = [
            "Where is the emergency transit ambulance going?",
            "Show me active emergency vehicle events",
            "What is the police cruiser preemption plan?",
        ]
        for query in queries:
            res = await nlu.execute(session, message=query)
            assert res.refused is True, f"Failed to refuse query: '{query}'"
            assert res.intent == "out_of_scope"
            assert "restricted to municipal control-room" in res.answer
            assert len(res.tools_used) == 0


@pytest.mark.anyio
async def test_citizen_asking_control_decisions_refused():
    """Verify citizen asking for AI supervisory control decisions is refused gracefully."""
    nlu = CitizenNLU()
    async with AsyncSessionLocal() as session:
        res = await nlu.execute(session, message="Why was green extended by the AI decision?")
        assert res.refused is True
        assert res.intent == "out_of_scope"
        assert len(res.tools_used) == 0


@pytest.mark.anyio
async def test_citizen_in_scope_how_to_report_and_general_help():
    """Verify in-scope how-to-report and general help intents return factual guidance."""
    nlu = CitizenNLU()
    async with AsyncSessionLocal() as session:
        # How to report
        res_report = await nlu.execute(session, message="How do I report a broken traffic signal?")
        assert res_report.intent == "how_to_report"
        assert res_report.refused is False
        assert "get_how_to_report" in res_report.tools_used
        assert "311" in res_report.answer or "emergency" in res_report.answer.lower()

        # General help
        res_help = await nlu.execute(session, message="What can you help me with?")
        assert res_help.intent == "general_help"
        assert res_help.refused is False
        assert "get_citizen_general_help" in res_help.tools_used
        assert "Public Citizen Assistant" in res_help.answer


# ==============================================================================
# 5. REST API POST /api/v1/citizen/chat TESTS & AUDIT TRAIL
# ==============================================================================


@pytest.mark.anyio
async def test_citizen_chat_api_success_and_provenance(
    async_client: AsyncClient,
    test_users: dict,
):
    """Verify POST /api/v1/citizen/chat returns structured response with provenance."""
    citizen_token = test_users["citizen"]["token"]

    resp = await async_client.post(
        "/api/v1/citizen/chat",
        headers={"Authorization": f"Bearer {citizen_token}"},
        json={"message": "What are current traffic conditions across the city?"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert "answer" in data
    assert data["provenance"] == "observed"
    assert data["refused"] is False
    assert "get_public_traffic_conditions" in data["tools_used"]
    assert data["confidence"] in ("high", "medium", "low")


@pytest.mark.anyio
async def test_citizen_chat_api_refusal_on_restricted_query(
    async_client: AsyncClient,
    test_users: dict,
):
    """Verify POST /api/v1/citizen/chat returns refused=true on signal timing request."""
    citizen_token = test_users["citizen"]["token"]

    resp = await async_client.post(
        "/api/v1/citizen/chat",
        headers={"Authorization": f"Bearer {citizen_token}"},
        json={"message": "Simulate signal timing for junction 1 with green split of 50s"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["refused"] is True
    assert "restricted to municipal control-room" in data["answer"]
    assert len(data["tools_used"]) == 0


@pytest.mark.anyio
async def test_citizen_chat_api_unauthenticated_rejected(
    async_client: AsyncClient,
):
    """Verify unauthenticated call to /api/v1/citizen/chat is rejected with 401 Unauthorized."""
    resp = await async_client.post(
        "/api/v1/citizen/chat",
        json={"message": "How is traffic right now?"},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_citizen_cannot_access_control_room_assistant_api(
    async_client: AsyncClient,
    test_users: dict,
):
    """Verify citizen role CANNOT access control-room /api/v1/assistant/chat (403 Forbidden)."""
    citizen_token = test_users["citizen"]["token"]

    resp = await async_client.post(
        "/api/v1/assistant/chat",
        headers={"Authorization": f"Bearer {citizen_token}"},
        json={"message": "Why was green extended at junction 1?"},
    )
    assert resp.status_code == 403, f"Citizen should be forbidden from control-room assistant, got: {resp.status_code}"


@pytest.mark.anyio
async def test_citizen_chat_audit_logging(
    async_client: AsyncClient,
    test_users: dict,
):
    """Verify citizen chat creates immutable audit log entries."""
    citizen_token = test_users["citizen"]["token"]
    citizen_id = test_users["citizen"]["id"]

    resp = await async_client.post(
        "/api/v1/citizen/chat",
        headers={"Authorization": f"Bearer {citizen_token}"},
        json={"message": "How do I report a traffic incident?"},
    )
    assert resp.status_code == 200

    async with AsyncSessionLocal() as session:
        stmt = (
            select(AuditLog)
            .where(
                AuditLog.action == "citizen.chat",
                AuditLog.actor_user_id == citizen_id,
            )
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
        res = await session.execute(stmt)
        entry = res.scalars().first()
        assert entry is not None
        assert entry.details["intent"] == "how_to_report"
        assert entry.details["refused"] is False
