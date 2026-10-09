"""Unit and integration tests for Gemini Conversational Assistant Provider (Batch 1 Fix 1).

Tests:
1. get_llm_provider() returns DeterministicProvider when no key is set (default unchanged).
2. get_llm_provider("gemini") without key -> DeterministicProvider.
3. get_llm_provider("gemini") with key -> GeminiProvider.
4. GeminiProvider with mocked httpx response returns conversational answer while
   preserving tool_calls, provenance, intent, and confidence from deterministic run.
5. GeminiProvider on API failure (HTTP error, connection error, timeout) -> falls back to deterministic answer.
6. GeminiProvider on empty candidates or empty text -> falls back to deterministic answer.
7. GeminiProvider with no API key -> returns deterministic answer without network calls.
8. End-to-end REST API POST /api/v1/assistant/chat with GeminiProvider configured:
   returns 200, conversational answer, tool_calls/provenance preserved, model='gemini', and audit log.
9. End-to-end REST API fallback to deterministic answer on API failure.
"""

from unittest.mock import AsyncMock, patch
import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.nlu import NLUResult
from app.assistant.providers import (
    DeterministicProvider,
    GeminiProvider,
    GEMINI_SYSTEM_INSTRUCTION,
    get_llm_provider,
)
from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.models.audit import AuditLog
from app.models.intersection import Intersection


@pytest.fixture
async def clean_engine_pool():
    """Ensure connection pool is disposed between tests."""
    yield
    await engine.dispose()


@pytest.fixture
async def ensure_test_intersections(clean_engine_pool):
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
# 1. PROVIDER FACTORY SELECTION TESTS
# ==============================================================================


def test_get_llm_provider_default_no_key(monkeypatch):
    """get_llm_provider() returns DeterministicProvider when no key is set (default unchanged)."""
    monkeypatch.setattr(settings, "ASSISTANT_LLM_PROVIDER", "deterministic")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
    monkeypatch.setattr(settings, "ASSISTANT_LLM_API_KEY", None)

    provider = get_llm_provider()
    assert isinstance(provider, DeterministicProvider)
    assert provider.name == "deterministic"


def test_get_llm_provider_gemini_without_key(monkeypatch):
    """get_llm_provider('gemini') without key -> DeterministicProvider."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
    monkeypatch.setattr(settings, "ASSISTANT_LLM_API_KEY", None)

    # Explicit provider_name argument
    provider_explicit = get_llm_provider("gemini")
    assert isinstance(provider_explicit, DeterministicProvider)
    assert provider_explicit.name == "deterministic"

    # Via settings.ASSISTANT_LLM_PROVIDER
    monkeypatch.setattr(settings, "ASSISTANT_LLM_PROVIDER", "gemini")
    provider_env = get_llm_provider()
    assert isinstance(provider_env, DeterministicProvider)
    assert provider_env.name == "deterministic"


def test_get_llm_provider_gemini_with_key(monkeypatch):
    """get_llm_provider('gemini') with key -> GeminiProvider."""
    fake_key = "AIzaSy_fake_test_key_for_unit_tests"
    monkeypatch.setattr(settings, "GEMINI_API_KEY", fake_key)
    monkeypatch.setattr(settings, "ASSISTANT_LLM_API_KEY", None)
    monkeypatch.setattr(settings, "ASSISTANT_LLM_PROVIDER", "deterministic")

    # Explicit call with 'gemini'
    provider = get_llm_provider("gemini")
    assert isinstance(provider, GeminiProvider)
    assert provider.name == "gemini"

    # Via settings.ASSISTANT_LLM_PROVIDER = 'gemini'
    monkeypatch.setattr(settings, "ASSISTANT_LLM_PROVIDER", "gemini")
    provider_from_settings = get_llm_provider()
    assert isinstance(provider_from_settings, GeminiProvider)
    assert provider_from_settings.name == "gemini"


def test_get_llm_provider_unknown_defaults_to_deterministic(monkeypatch):
    """Unknown provider string cleanly defaults to DeterministicProvider."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
    provider = get_llm_provider("nonexistent-vendor")
    assert isinstance(provider, DeterministicProvider)
    assert provider.name == "deterministic"


def test_gemini_model_configuration_and_env_override(monkeypatch):
    """GEMINI_MODEL environment variable overrides the default model name in Settings and GeminiProvider."""
    # 1. Default model is gemini-3.8-flash (late-2026 stable Flash default)
    assert settings.GEMINI_MODEL == "gemini-3.8-flash"
    default_provider = GeminiProvider(api_key="fake-key")
    assert default_provider.model == "gemini-3.8-flash"

    # 2. Override via environment variable in pydantic Settings
    custom_model = "gemini-2.0-flash-override"
    monkeypatch.setenv("GEMINI_MODEL", custom_model)
    from app.core.config import Settings
    reloaded_settings = Settings()
    assert reloaded_settings.GEMINI_MODEL == custom_model

    # 3. Setting on settings singleton propagates to GeminiProvider and factory
    monkeypatch.setattr(settings, "GEMINI_MODEL", custom_model)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "fake-key")
    env_provider = GeminiProvider()
    assert env_provider.model == custom_model

    factory_provider = get_llm_provider("gemini")
    assert isinstance(factory_provider, GeminiProvider)
    assert factory_provider.model == custom_model

    # 4. Explicit model parameter overrides settings.GEMINI_MODEL
    explicit_provider = GeminiProvider(model="gemini-explicit-param")
    assert explicit_provider.model == "gemini-explicit-param"


@pytest.mark.anyio
async def test_gemini_provider_model_env_override_propagates_to_rest_api(
    monkeypatch, ensure_test_intersections
):
    """Overridden GEMINI_MODEL via env var is correctly included in the generateContent REST URL."""
    fake_key = "AIzaSy_mock_gemini_api_key"
    override_model = "gemini-2.5-flash-test"
    monkeypatch.setattr(settings, "GEMINI_MODEL", override_model)

    captured_urls = []

    def mock_post(url, **kwargs):
        captured_urls.append(str(url))
        return httpx.Response(
            status_code=200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": "Conversational test response."}],
                            "role": "model",
                        },
                        "finishReason": "STOP",
                    }
                ]
            },
            request=httpx.Request("POST", str(url)),
        )

    async with AsyncSessionLocal() as session:
        provider = GeminiProvider(api_key=fake_key)
        assert provider.model == override_model

        context = {
            "db": session,
            "caller_role": "admin",
        }

        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=mock_post)):
            result = await provider.process_query(
                prompt="Which junctions are most congested right now?",
                context=context,
            )

        assert isinstance(result, NLUResult)
        assert result.answer == "Conversational test response."
        assert len(captured_urls) == 1
        assert f"models/{override_model}:generateContent" in captured_urls[0]
        await session.rollback()


# ==============================================================================
# 2. GEMINI PROVIDER GROUNDED EXECUTION & CONVERSATIONAL RENDERING
# ==============================================================================


@pytest.mark.anyio
async def test_gemini_provider_mocked_success(ensure_test_intersections):
    """GeminiProvider with mocked httpx response returns conversational answer while preserving metadata."""
    fake_key = "AIzaSy_mock_gemini_api_key"
    conversational_text = (
        "Based on current real-time monitoring data, Junction 1 is experiencing peak congestion "
        "at 78% capacity. Prediction models indicate a slight easing over the next 30 minutes, "
        "and supervisory coordination recommends extending Phase 2 green timing."
    )

    captured_requests = []

    def mock_post(url, headers=None, json=None, **kwargs):
        captured_requests.append({"url": str(url), "headers": headers, "json": json})
        resp = httpx.Response(
            status_code=200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [{"text": conversational_text}],
                            "role": "model",
                        },
                        "finishReason": "STOP",
                    }
                ]
            },
            request=httpx.Request("POST", str(url)),
        )
        return resp

    async with AsyncSessionLocal() as session:
        provider = GeminiProvider(api_key=fake_key)
        context = {
            "db": session,
            "caller_role": "admin",
        }

        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=mock_post)):
            result = await provider.process_query(
                prompt="Which junctions are most congested right now?",
                context=context,
            )

        # 1. Output contract
        assert isinstance(result, NLUResult)
        assert result.answer == conversational_text
        assert result.intent == "congested_junctions"
        assert len(result.tool_calls) >= 1
        assert result.tool_calls[0]["tool"] == "get_congestion_ranking"
        assert result.tool_calls[0]["provenance"] == "observed"
        assert isinstance(result.provenance_summary, dict)
        assert "observed" in result.provenance_summary
        assert result.confidence in ("high", "medium", "low")

        # 2. Complete() helper returns answer
        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=mock_post)):
            completed_text = await provider.complete(
                prompt="Which junctions are most congested right now?",
                context=context,
            )
            assert completed_text == conversational_text

        # 3. Verify request details
        assert len(captured_requests) >= 1
        req = captured_requests[0]
        assert f"models/{settings.GEMINI_MODEL}:generateContent" in req["url"]
        assert req["headers"].get("x-goog-api-key") == fake_key
        assert req["headers"].get("Content-Type") == "application/json"
        assert req["json"]["system_instruction"]["parts"][0]["text"] == GEMINI_SYSTEM_INSTRUCTION
        # Grounded answer was passed to rephrase
        assert len(req["json"]["contents"][0]["parts"][0]["text"]) > 0

        await session.rollback()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "error_instance",
    [
        httpx.HTTPStatusError(
            "403 Forbidden",
            request=httpx.Request("POST", "http://test"),
            response=httpx.Response(403, request=httpx.Request("POST", "http://test")),
        ),
        httpx.HTTPStatusError(
            "500 Internal Server Error",
            request=httpx.Request("POST", "http://test"),
            response=httpx.Response(500, request=httpx.Request("POST", "http://test")),
        ),
        httpx.ConnectError("Connection refused"),
        httpx.TimeoutException("Request timed out"),
        httpx.NetworkError("Network unreachable"),
    ],
)
async def test_gemini_provider_api_failure_fallback(error_instance, ensure_test_intersections):
    """On any Gemini API failure (network error, 4xx/5xx, timeout), silently falls back to deterministic answer."""
    fake_key = "AIzaSy_mock_gemini_api_key"

    async with AsyncSessionLocal() as session:
        provider = GeminiProvider(api_key=fake_key)
        context = {
            "db": session,
            "caller_role": "admin",
        }

        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=error_instance)):
            # Must NOT raise exception to the caller
            result = await provider.process_query(
                prompt="Which junctions are most congested right now?",
                context=context,
            )

        assert isinstance(result, NLUResult)
        # Deterministic answer preserved
        assert "### Observed Traffic Telemetry" in result.answer
        assert result.intent == "congested_junctions"
        assert len(result.tool_calls) >= 1
        assert "observed" in result.provenance_summary

        await session.rollback()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "bad_payload",
    [
        {"candidates": []},
        {"candidates": [{"content": {"parts": []}}]},
        {"candidates": [{"content": {"parts": [{"text": ""}]}}]},
        {"candidates": [{"content": {"parts": [{"text": "   \n\t  "}]}}]},
        {"error": {"code": 400, "message": "Invalid request"}},
    ],
)
async def test_gemini_provider_malformed_response_fallback(bad_payload, ensure_test_intersections):
    """When Gemini returns an empty/malformed payload, falls back silently to deterministic answer."""
    fake_key = "AIzaSy_mock_gemini_api_key"

    def mock_post(url, **kwargs):
        return httpx.Response(
            status_code=200,
            json=bad_payload,
            request=httpx.Request("POST", str(url)),
        )

    async with AsyncSessionLocal() as session:
        provider = GeminiProvider(api_key=fake_key)
        context = {
            "db": session,
            "caller_role": "admin",
        }

        with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=mock_post)):
            result = await provider.process_query(
                prompt="Which junctions are most congested right now?",
                context=context,
            )

        assert isinstance(result, NLUResult)
        assert "### Observed Traffic Telemetry" in result.answer
        assert result.intent == "congested_junctions"
        assert len(result.tool_calls) >= 1

        await session.rollback()


@pytest.mark.anyio
async def test_gemini_provider_no_key_bypasses_http(monkeypatch, ensure_test_intersections):
    """When GeminiProvider is initialized without a key, returns deterministic answer without any HTTP calls."""
    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
    monkeypatch.setattr(settings, "ASSISTANT_LLM_API_KEY", None)

    async with AsyncSessionLocal() as session:
        provider = GeminiProvider(api_key=None)
        context = {
            "db": session,
            "caller_role": "admin",
        }

        with patch("httpx.AsyncClient.post", new=AsyncMock()) as mock_post:
            result = await provider.process_query(
                prompt="Are there any active incidents right now?",
                context=context,
            )
            # No network call performed
            mock_post.assert_not_called()

        assert isinstance(result, NLUResult)
        assert result.intent == "active_incidents"
        assert len(result.answer) > 0

        await session.rollback()


# ==============================================================================
# 3. END-TO-END REST API CHAT INTEGRATION (POST /api/v1/assistant/chat)
# ==============================================================================


@pytest.mark.anyio
async def test_assistant_chat_with_gemini_provider_success(
    async_client: httpx.AsyncClient,
    test_users: dict,
    monkeypatch,
    ensure_test_intersections,
):
    """With ASSISTANT_LLM_PROVIDER='gemini' and valid key, chat endpoint returns conversational answer."""
    fake_key = "AIzaSy_mock_gemini_key_for_api_test"
    monkeypatch.setattr(settings, "ASSISTANT_LLM_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", fake_key)

    token = test_users["admin"]["token"]
    conversational_text = (
        "Citywide traffic status report: Currently no major structural blockages are recorded. "
        "All 6 monitored intersections are functioning normally."
    )

    original_post = httpx.AsyncClient.post

    async def selective_mock_post(self, url, *args, **kwargs):
        if "generativelanguage.googleapis.com" in str(url):
            return httpx.Response(
                status_code=200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [{"text": conversational_text}],
                                "role": "model",
                            },
                            "finishReason": "STOP",
                        }
                    ]
                },
                request=httpx.Request("POST", str(url)),
            )
        return await original_post(self, url, *args, **kwargs)

    with patch.object(httpx.AsyncClient, "post", selective_mock_post):
        resp = await async_client.post(
            "/api/v1/assistant/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "Are there any active incidents right now?"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["answer"] == conversational_text
    assert data["model"] == "gemini"
    assert len(data["tool_calls"]) >= 1
    assert data["tool_calls"][0]["tool"] == "get_incidents"
    assert data["tool_calls"][0]["provenance"] == "observed"

    # Verify audit log recorded model='gemini'
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
        assert entry.details["model"] == "gemini"
        assert entry.details["intent"] == "active_incidents"
        await session.rollback()


@pytest.mark.anyio
async def test_assistant_chat_with_gemini_provider_fallback_on_network_error(
    async_client: httpx.AsyncClient,
    test_users: dict,
    monkeypatch,
    ensure_test_intersections,
):
    """With ASSISTANT_LLM_PROVIDER='gemini', if Gemini fails, chat endpoint falls back to deterministic answer."""
    fake_key = "AIzaSy_mock_gemini_key_for_api_test"
    monkeypatch.setattr(settings, "ASSISTANT_LLM_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", fake_key)

    token = test_users["admin"]["token"]
    original_post = httpx.AsyncClient.post

    async def selective_mock_post(self, url, *args, **kwargs):
        if "generativelanguage.googleapis.com" in str(url):
            raise httpx.ConnectError("Simulated network outage to Google API")
        return await original_post(self, url, *args, **kwargs)

    with patch.object(httpx.AsyncClient, "post", selective_mock_post):
        resp = await async_client.post(
            "/api/v1/assistant/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"message": "Which junctions are most congested right now?"},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "### Observed Traffic Telemetry" in data["answer"]
    assert data["model"] == "gemini"
    assert len(data["tool_calls"]) >= 1
    assert data["tool_calls"][0]["tool"] == "get_congestion_ranking"
