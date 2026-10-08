"""Comprehensive tests for AI Assistant module (Phase 9 Stage 4).

Covers:
1. Tool-level RBAC enforcement and data grounding invariants (observed/predicted/recommended).
2. Grounded deterministic NLU intent classification, entity extraction, and template answers.
3. Nonexistent / ambiguous junction error handling without data fabrication.
4. LLM provider abstraction (DeterministicProvider and HttpLLMProvider extension point).
5. REST API POST /api/v1/assistant/chat behavior across roles (admin, analyst), RBAC error messages,
   and audit logging.
"""

from httpx import AsyncClient
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.errors import JunctionNotFoundError, PermissionDeniedError
from app.assistant.nlu import (
    DeterministicNLUEngine,
    extract_numeric_junction_id,
    extract_route_endpoints,
    extract_whatif_parameters,
    resolve_junction_carryover,
)
from app.assistant.providers import (
    DeterministicProvider,
    HttpLLMProvider,
    get_llm_provider,
)
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


@pytest.fixture(autouse=True)
async def clean_engine_pool():
    """Ensure connection pool is disposed between tests to prevent event loop mismatch."""
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def ensure_test_intersections():
    """Ensure baseline test intersections 1..6 exist for assistant tests."""
    from sqlalchemy import text

    async with AsyncSessionLocal() as session:
        for jid in (1, 2, 3, 4, 5, 6):
            existing = await session.get(Intersection, jid)
            if not existing:
                inter = Intersection(
                    id=jid,
                    name=f"Test Junction {jid}",
                    code=f"INT-{jid:03d}",
                    status="active",
                    city="Metropolis",
                    zone="Downtown",
                    lat=37.7749 + (jid * 0.001),
                    lon=-122.4194 + (jid * 0.001),
                )
                session.add(inter)
        await session.commit()
        await session.execute(
            text("SELECT setval('intersections_id_seq', (SELECT coalesce(max(id), 1) FROM intersections))")
        )
        await session.commit()


# ==============================================================================
# 1. TOOL LAYER UNIT TESTS & RBAC MATRIX
# ==============================================================================


@pytest.mark.anyio
async def test_tools_rbac_matrix_and_provenance():
    """Verify tool RBAC restrictions and strict provenance tagging on return values."""
    async with AsyncSessionLocal() as session:
        # Read-only tools allow analyst
        traffic_res = await get_traffic_state(session, caller_role="analyst", junction_id=None)
        assert traffic_res["provenance"] == "observed"

        ranking_res = await get_congestion_ranking(session, caller_role="analyst", limit=5)
        assert ranking_res["provenance"] == "observed"

        pred_res = await get_predictions_30min(session, caller_role="analyst", junction_id=None)
        assert pred_res["provenance"] == "predicted"

        inc_res = await get_incidents(session, caller_role="analyst", active_only=True)
        assert inc_res["provenance"] == "observed"

        sig_res = await get_signal_status(session, caller_role="analyst", junction_id=None)
        assert sig_res["provenance"] == "observed"

        dec_res = await get_control_decisions(session, caller_role="analyst", limit=5)
        assert dec_res["provenance"] == "recommended"

        summary_res = await get_analytics_summary(session, caller_role="analyst")
        assert summary_res["provenance"] == "observed"
        assert "total_intersections" in summary_res["data"]

        em_res = await get_emergency_events(session, caller_role="analyst", active_only=True)
        assert em_res["provenance"] == "observed"

        # Operator-only tools MUST reject analyst with PermissionDeniedError
        with pytest.raises(PermissionDeniedError) as exc_info:
            await get_routing_advice(session, caller_role="analyst", origin_id=1, destination_id=2)
        assert exc_info.value.role == "analyst"
        assert exc_info.value.domain == "routing_advice"

        with pytest.raises(PermissionDeniedError) as exc_info:
            await simulate_signal_timing(session, caller_role="analyst", junction_id=1, green_seconds=45)
        assert exc_info.value.role == "analyst"
        assert exc_info.value.domain == "simulate_signal_timing"
        await session.rollback()


@pytest.mark.anyio
async def test_tools_operator_permissions():
    """Verify admin / traffic_officer can invoke operator tools successfully."""
    async with AsyncSessionLocal() as session:
        # Test routing advice with real intersections 1 and 2
        j1 = await session.get(Intersection, 1)
        j2 = await session.get(Intersection, 2)
        if j1 and j2:
            route_res = await get_routing_advice(session, caller_role="admin", origin_id=1, destination_id=2)
            assert route_res["provenance"] == "recommended"
            assert "confidence" in route_res
        await session.rollback()


@pytest.mark.anyio
async def test_tools_nonexistent_junction_raises_cleanly():
    """Querying a nonexistent junction raises JunctionNotFoundError, never fabricating data."""
    async with AsyncSessionLocal() as session:
        with pytest.raises(JunctionNotFoundError) as exc_info:
            await get_traffic_state(session, caller_role="admin", junction_id=999999)
        assert exc_info.value.identifier == 999999
        await session.rollback()


# ==============================================================================
# 2. NLU ENGINE UNIT TESTS
# ==============================================================================


@pytest.mark.anyio
async def test_nlu_intent_classification():
    """Verify regex intent matching across required domains."""
    engine = DeterministicNLUEngine()
    assert engine.classify_intent("Which junctions are most congested right now?") == "congested_junctions"
    assert engine.classify_intent("Where are the worst traffic areas in the city?") == "worst_traffic_areas"
    assert engine.classify_intent("Are there any active incidents right now?") == "active_incidents"
    assert engine.classify_intent("What is the predicted traffic in 30 minutes at junction 2?") == "predicted_congestion_30min"
    assert engine.classify_intent("How do I get from junction 1 to junction 4?") == "route_advice"
    assert engine.classify_intent("What happened at junction 2 in the past 24 hours?") == "junction_history"
    assert engine.classify_intent("Why was green extended at junction 2?") == "why_green_extended"
    assert engine.classify_intent("Why was this signal recommendation proposed?") == "why_signal_recommendation"
    assert engine.classify_intent("What if green were 45 seconds at junction 6?") == "whatif_signal_timing"
    assert engine.classify_intent("What is the traffic situation at junction 2?") == "current_traffic_situation"
    # Task C natural phrasings
    assert engine.classify_intent("Which junctions are congested?") == "congested_junctions"
    assert engine.classify_intent("What route should traffic take?") == "route_advice"
    assert engine.classify_intent("What would happen if this signal timing changed?") == "whatif_signal_timing"
    # General chitchat / unknown intent
    assert engine.classify_intent("What is the capital of France?") == "unknown"


@pytest.mark.anyio
async def test_nlu_entity_extraction_helpers():
    """Verify regex entity extraction utilities."""
    assert extract_numeric_junction_id("How is traffic at junction 12?") == 12
    assert extract_numeric_junction_id("Status for intersection #7") == 7
    assert extract_numeric_junction_id("Random text without numbers") is None

    orig, dest = extract_route_endpoints("How do I get from junction 3 to junction 8?")
    assert orig == 3 and dest == 8

    j_id, sec = extract_whatif_parameters("What if green were 45 seconds at junction 6?")
    assert j_id == 6 and sec == 45

    # Carryover from conversation history
    history = [
        {"role": "user", "content": "How is traffic at junction 3?"},
        {"role": "assistant", "content": "Junction 3 has 45% congestion."},
    ]
    assert resolve_junction_carryover(history) == 3


@pytest.mark.anyio
async def test_nlu_graceful_unknown_question():
    """Verify unknown questions return graceful can't-answer response with suggestions."""
    async with AsyncSessionLocal() as session:
        engine = DeterministicNLUEngine()
        result = await engine.execute(
            db=session,
            message="What is the capital of France?",
            caller_role="admin",
        )
        assert result.intent == "unknown"
        assert "I can't answer that from system data" in result.answer
        assert "Which junctions are most congested right now?" in result.answer
        await session.rollback()


@pytest.mark.anyio
async def test_nlu_nonexistent_junction_clarification():
    """Verify asking about junction 99999 returns clarification naming real junctions."""
    async with AsyncSessionLocal() as session:
        engine = DeterministicNLUEngine()
        result = await engine.execute(
            db=session,
            message="What is the traffic situation at junction 99999?",
            caller_role="admin",
        )
        assert "Junction 99999 does not exist in the system" in result.answer
        assert "Available intersections in the network include:" in result.answer
        await session.rollback()


# ==============================================================================
# 3. PROVIDER INTERFACE TESTS
# ==============================================================================


@pytest.mark.anyio
async def test_llm_providers():
    """Verify DeterministicProvider execution and get_llm_provider factory."""
    async with AsyncSessionLocal() as session:
        provider = get_llm_provider("deterministic")
        assert isinstance(provider, DeterministicProvider)
        assert provider.name == "deterministic"

        context = {
            "db": session,
            "caller_role": "admin",
        }
        answer = await provider.complete("Which junctions are most congested right now?", context)
        assert "### Observed Traffic Telemetry" in answer

        # Verify HttpLLMProvider extension point falls back when unconfigured
        http_provider = HttpLLMProvider(api_key=None, endpoint_url=None)
        fallback_res = await http_provider.process_query("Are there any active incidents?", context)
        assert fallback_res.intent == "active_incidents"
        await session.rollback()


# ==============================================================================
# 4. REST API INTEGRATION TESTS (POST /api/v1/assistant/chat)
# ==============================================================================


@pytest.mark.anyio
async def test_assistant_chat_congested_junctions_admin(
    async_client: AsyncClient,
    test_users: dict,
):
    """As admin: ask congested junctions -> response cites tool calls and observed provenance."""
    token = test_users["admin"]["token"]
    resp = await async_client.post(
        "/api/v1/assistant/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Which junctions are most congested right now?"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "answer" in data
    assert "### Observed Traffic Telemetry" in data["answer"]
    assert len(data["tool_calls"]) >= 1
    assert data["tool_calls"][0]["tool"] == "get_congestion_ranking"
    assert data["tool_calls"][0]["provenance"] == "observed"
    assert data["model"] == "deterministic"

    # Verify audit log was recorded in DB
    async with AsyncSessionLocal() as session:
        audit_stmt = (
            select(AuditLog)
            .where(AuditLog.action == "assistant.chat")
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        res = await session.execute(audit_stmt)
        entry = res.scalars().first()
        assert entry is not None
        assert entry.action == "assistant.chat"
        assert entry.entity_type == "assistant"
        assert entry.details["intent"] == "congested_junctions"
        await session.rollback()


@pytest.mark.anyio
async def test_assistant_chat_analyst_rbac_enforcement(
    async_client: AsyncClient,
    test_users: dict,
):
    """As analyst: ask for what-if simulation (operator tool) -> clean RBAC denial message."""
    token = test_users["analyst"]["token"]
    resp = await async_client.post(
        "/api/v1/assistant/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "What if green were 45 seconds at junction 6?"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "Your role (analyst) doesn't include simulate_signal_timing" in data["answer"]
    assert "Operator permissions" in data["answer"]


@pytest.mark.anyio
async def test_assistant_chat_why_green_extended_grounding(
    async_client: AsyncClient,
    test_users: dict,
):
    """Test why_green_extended returns honest grounded response or 'no such decision found'."""
    token = test_users["admin"]["token"]
    # Ask about junction 2
    resp = await async_client.post(
        "/api/v1/assistant/chat",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": "Why was green extended at junction 2?"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # Junction 2 has real decisions in DB (or if none, returns honest statement)
    assert "### Observed Traffic Telemetry" in data["answer"]
    assert "### System Recommendations" in data["answer"]


@pytest.mark.anyio
async def test_assistant_chat_unauthenticated(async_client: AsyncClient):
    """Unauthenticated calls are rejected with 401 Unauthorized."""
    resp = await async_client.post(
        "/api/v1/assistant/chat",
        json={"message": "How is traffic right now?"},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_ten_required_questions_nlu_coverage(
    async_client: AsyncClient,
    test_users: dict,
):
    """Assert each of the 10 required questions verbatim reaches its intended tool/intent and never unknown.

    Verified questions:
    1. 'Which junctions are congested?' -> congested_junctions
    2. 'Where are the worst traffic areas in the city?' -> worst_traffic_areas
    3. 'Are there any active incidents right now?' -> active_incidents
    4. 'What is the predicted traffic in 30 minutes at junction 2?' -> predicted_congestion_30min
    5. 'What route should traffic take?' -> route_advice
    6. 'What happened at junction 2 in the past 24 hours?' -> junction_history
    7. 'Why was green extended at junction 2?' -> why_green_extended
    8. 'Why was this signal recommendation proposed?' -> why_signal_recommendation
    9. 'What would happen if this signal timing changed?' -> whatif_signal_timing
    10. 'What is the traffic situation at junction 2?' -> current_traffic_situation
    """
    token = test_users["admin"]["token"]
    required_questions = [
        ("Which junctions are congested?", "congested_junctions"),
        ("Where are the worst traffic areas in the city?", "worst_traffic_areas"),
        ("Are there any active incidents right now?", "active_incidents"),
        ("What is the predicted traffic in 30 minutes at junction 2?", "predicted_congestion_30min"),
        ("What route should traffic take?", "route_advice"),
        ("What happened at junction 2 in the past 24 hours?", "junction_history"),
        ("Why was green extended at junction 2?", "why_green_extended"),
        ("Why was this signal recommendation proposed?", "why_signal_recommendation"),
        ("What would happen if this signal timing changed?", "whatif_signal_timing"),
        ("What is the traffic situation at junction 2?", "current_traffic_situation"),
    ]

    engine = DeterministicNLUEngine()
    for question, expected_intent in required_questions:
        # 1. Deterministic NLU classifier check
        classified = engine.classify_intent(question)
        assert classified == expected_intent, f"Expected intent {expected_intent} for '{question}', got {classified}"
        assert classified != "unknown"

        # 2. REST API /assistant/chat execution check
        resp = await async_client.post(
            "/api/v1/assistant/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": question},
        )
        assert resp.status_code == 200, f"Error on question '{question}': {resp.text}"
        data = resp.json()
        assert "I can't answer that from system data" not in data["answer"], (
            f"Question '{question}' fell through to unknown fallback: {data['answer']}"
        )
