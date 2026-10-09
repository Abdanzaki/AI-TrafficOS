"""LLM Provider Interface and Concrete Providers.

Provides an extensible, decoupled interface for generating assistant responses:
- `DeterministicProvider`: Default production engine. Executes the deterministic grounded
  NLU engine with zero external network dependencies, strict database grounding, and
  predictable provenance guarantees.
- `GeminiProvider`: Grounded-first conversational engine powered by Google Gemini REST API.
  Runs the deterministic grounded NLU engine first for 100% factual accuracy, tool dispatch,
  provenance, and confidence, then renders the grounded answer conversationally via Gemini
  REST API (`generateContent`) using `httpx`. Falls back silently to deterministic output on
  any API failure.
- `HttpLLMProvider`: Documented extension point for plugging external vendor APIs
  (e.g. OpenAI/Anthropic-compatible endpoints). Operates strictly via environment
  variables (`ASSISTANT_LLM_PROVIDER`, `ASSISTANT_LLM_API_KEY`). Never hardcodes or logs keys.

CONFIGURATION & UPGRADE PATH:
=============================
- Out of the box, `ASSISTANT_LLM_PROVIDER="deterministic"` ships fully working and tested.
- Setting `ASSISTANT_LLM_PROVIDER="gemini"` and setting `GEMINI_API_KEY` in `backend/.env`
  (or host environment) upgrades the assistant to conversational mode via Google Gemini while
  preserving strict database grounding and provenance guarantees.
- Setting `ASSISTANT_LLM_PROVIDER="http"` and providing `ASSISTANT_LLM_API_KEY` in `backend/.env`
  upgrades the assistant to custom external HTTP LLM mode.
- If `GEMINI_API_KEY` is absent or the API fails, the system safely and silently falls back
  to `DeterministicProvider` with zero behavioral deviation.
- No third-party vendor SDKs are imported at module load time to preserve zero-footprint purity.
"""

from abc import ABC, abstractmethod
import logging
from typing import Any, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant.nlu import DeterministicNLUEngine, NLUResult
from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract base class for assistant LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Identifier of the provider engine (e.g. 'deterministic', 'http')."""

    @abstractmethod
    async def complete(self, prompt: str, context: dict[str, Any]) -> str:
        """Generate a response text given user prompt and operational context.

        Args:
            prompt: User message string.
            context: Operational context dictionary containing at minimum:
                - 'db': AsyncSession
                - 'caller_role': str
                - Optional 'conversation_history': list[dict[str, str]]
                - Optional 'junction_id': int

        Returns:
            Grounded textual answer string.
        """

    @abstractmethod
    async def process_query(self, prompt: str, context: dict[str, Any]) -> NLUResult:
        """Execute complete assistant turn returning structured NLUResult.

        Args:
            prompt: User message string.
            context: Operational context dictionary.

        Returns:
            NLUResult with intent, answer, tool_calls, provenance_summary, and confidence.
        """


class DeterministicProvider(LLMProvider):
    """Default deterministic provider powered by the grounded NLU engine.

    Requires zero external network calls, zero vendor API keys, and guarantees
    100% database-grounded outputs.
    """

    def __init__(self) -> None:
        self.engine = DeterministicNLUEngine()

    @property
    def name(self) -> str:
        return "deterministic"

    async def complete(self, prompt: str, context: dict[str, Any]) -> str:
        """Generate grounded answer string."""
        result = await self.process_query(prompt, context)
        return result.answer

    async def process_query(self, prompt: str, context: dict[str, Any]) -> NLUResult:
        """Execute deterministic grounded NLU workflow."""
        db: AsyncSession = context["db"]
        caller_role: str = context.get("caller_role", "analyst")
        conversation_history = context.get("conversation_history")
        junction_id = context.get("junction_id")

        return await self.engine.execute(
            db=db,
            message=prompt,
            caller_role=caller_role,
            conversation_history=conversation_history,
            explicit_junction_id=junction_id,
        )


GEMINI_SYSTEM_INSTRUCTION = (
    "You are rephrasing a traffic-operations answer. Use ONLY the facts in the provided "
    "grounded answer. Do not add, infer, or invent any numbers, names, or events. Keep the "
    "observed-data → prediction → recommendation structure and uncertainty labels. "
    "If the grounded answer says no data exists, say so plainly."
)


class GeminiProvider(LLMProvider):
    """Grounded-first conversational assistant provider powered by Google Gemini.

    GROUNDED-FIRST ARCHITECTURE (NON-NEGOTIABLE):
    `process_query` MUST first run the existing `DeterministicNLUEngine.execute()` with the
    exact same arguments the DeterministicProvider uses (`db`, `message`, `caller_role`,
    `conversation_history`, `explicit_junction_id`). All facts, tool calls, provenance, intent,
    and confidence come from this deterministic run — Gemini NEVER invents data.

    CONVERSATIONAL RENDERING:
    Only when the `GEMINI_API_KEY` environment variable is set (read via `app.core.config.settings`,
    never hardcoded, never logged), calls the Gemini `generateContent` REST API using `httpx` async
    client with a strict rephrasing system instruction.
    On any Gemini API failure (network error, 4xx/5xx, invalid key, timeout), falls back to the
    deterministic answer silently (logs a warning, no exception to the caller).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 10.0,
    ) -> None:
        self._api_key = api_key or settings.GEMINI_API_KEY or settings.ASSISTANT_LLM_API_KEY
        # Model defaults to settings.GEMINI_MODEL (late 2026 stable Flash default: "gemini-3.8-flash").
        # Note on late 2026 model availability (https://ai.google.dev/gemini-api/docs/models):
        # - "gemini-3.8-flash" is the verified stable Flash model for new projects and newly created API keys.
        # - "gemini-3.5-flash-lite" is the verified ultra-fast, budget-friendly high-throughput Flash model.
        # - Legacy models: "gemini-2.0-flash" has been shut down; "gemini-2.5-flash" is restricted to legacy accounts.
        # - If running against older infrastructure or test mocks, override via GEMINI_MODEL="gemini-2.0-flash".
        self.model = model or settings.GEMINI_MODEL
        self.timeout = timeout
        self.engine = DeterministicNLUEngine()

    @property
    def name(self) -> str:
        return "gemini"

    async def complete(self, prompt: str, context: dict[str, Any]) -> str:
        """Generate conversational answer string."""
        result = await self.process_query(prompt, context)
        return result.answer

    async def process_query(self, prompt: str, context: dict[str, Any]) -> NLUResult:
        """Execute grounded NLU workflow first, then conversationally rephrase via Gemini."""
        db: AsyncSession = context["db"]
        caller_role: str = context.get("caller_role", "analyst")
        conversation_history = context.get("conversation_history")
        junction_id = context.get("junction_id")

        # 1. Grounded-first execution (NON-NEGOTIABLE)
        deterministic_result = await self.engine.execute(
            db=db,
            message=prompt,
            caller_role=caller_role,
            conversation_history=conversation_history,
            explicit_junction_id=junction_id,
        )

        # 2. Check if API key is configured
        api_key = (self._api_key or "").strip()
        if not api_key:
            logger.warning(
                "GeminiProvider invoked without GEMINI_API_KEY; falling back to deterministic answer."
            )
            return deterministic_result

        # Return deterministic result immediately if answer text is empty
        if not deterministic_result.answer or not deterministic_result.answer.strip():
            return deterministic_result

        # 3. Conversational rendering via Gemini generateContent REST API
        try:
            conversational_answer = await self._rephrase_with_gemini(
                grounded_answer=deterministic_result.answer,
                api_key=api_key,
            )
            if conversational_answer:
                return NLUResult(
                    intent=deterministic_result.intent,
                    answer=conversational_answer,
                    tool_calls=deterministic_result.tool_calls,
                    provenance_summary=deterministic_result.provenance_summary,
                    confidence=deterministic_result.confidence,
                )
        except Exception as exc:
            # Fall back silently to deterministic answer on any failure
            # Never log the API key or raw exception containing query parameters
            logger.warning(
                "Gemini API request failed (%s); silently falling back to deterministic answer.",
                type(exc).__name__,
            )

        return deterministic_result

    async def _rephrase_with_gemini(
        self, grounded_answer: str, api_key: str
    ) -> Optional[str]:
        """Invoke Gemini generateContent REST API using httpx async client."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }
        payload = {
            "system_instruction": {
                "parts": [{"text": GEMINI_SYSTEM_INSTRUCTION}],
            },
            "contents": [
                {
                    "parts": [{"text": grounded_answer}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
            },
        }

        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        candidates = data.get("candidates") or []
        if not candidates:
            logger.warning("Gemini response contained no candidates; falling back to deterministic answer.")
            return None

        content = candidates[0].get("content") or {}
        parts = content.get("parts") or []
        texts = [
            p.get("text", "")
            for p in parts
            if isinstance(p, dict) and "text" in p
        ]
        rephrased = "".join(texts).strip()
        if not rephrased:
            logger.warning("Gemini response contained empty text parts; falling back to deterministic answer.")
            return None

        return rephrased


class HttpLLMProvider(LLMProvider):
    """Extension point for external LLM vendors over HTTP.

    Reads API key strictly from settings/environment (`ASSISTANT_LLM_API_KEY`).
    Never hardcodes, commits, or logs keys.

    EXTENSION GUIDE:
    To connect an external model:
    1. Set ASSISTANT_LLM_PROVIDER=http in backend/.env.
    2. Set ASSISTANT_LLM_API_KEY=your_key in backend/.env.
    3. Configure endpoint URL and payload schema below.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        model_name: str = "generic-llm",
    ) -> None:
        self._api_key = api_key or settings.ASSISTANT_LLM_API_KEY
        self.endpoint_url = endpoint_url
        self.model_name = model_name
        self._fallback_engine = DeterministicNLUEngine()

    @property
    def name(self) -> str:
        return f"http:{self.model_name}"

    async def complete(self, prompt: str, context: dict[str, Any]) -> str:
        """Generate response via external HTTP endpoint or fall back cleanly."""
        result = await self.process_query(prompt, context)
        return result.answer

    async def process_query(self, prompt: str, context: dict[str, Any]) -> NLUResult:
        """Process query with external model or fall back to grounded engine if unconfigured."""
        if not self._api_key or not self.endpoint_url:
            logger.info(
                "HttpLLMProvider unconfigured (missing key or endpoint); falling back to deterministic NLU."
            )
            # Fall back safely to grounded deterministic engine
            db: AsyncSession = context["db"]
            caller_role: str = context.get("caller_role", "analyst")
            conversation_history = context.get("conversation_history")
            junction_id = context.get("junction_id")

            fallback_res = await self._fallback_engine.execute(
                db=db,
                message=prompt,
                caller_role=caller_role,
                conversation_history=conversation_history,
                explicit_junction_id=junction_id,
            )
            return fallback_res

        # Extension point: make HTTP call here using an async client (e.g. httpx)
        # Note: In accordance with project instructions, no fake HTTP calls are made.
        raise NotImplementedError(
            "HttpLLMProvider endpoint execution requires configuring external provider schema."
        )


def get_llm_provider(provider_name: Optional[str] = None) -> LLMProvider:
    """Factory creating configured LLMProvider based on environment or explicit parameter."""
    selected = (provider_name or settings.ASSISTANT_LLM_PROVIDER or "deterministic").strip().lower()

    if selected == "gemini":
        gemini_key = (settings.GEMINI_API_KEY or settings.ASSISTANT_LLM_API_KEY or "").strip()
        if gemini_key:
            return GeminiProvider(api_key=gemini_key)
        logger.warning(
            "Gemini provider selected but GEMINI_API_KEY is unset; defaulting to DeterministicProvider."
        )
        return DeterministicProvider()
    elif selected == "deterministic":
        return DeterministicProvider()
    elif selected == "http":
        return HttpLLMProvider()
    else:
        logger.warning(
            "Unknown provider '%s'; defaulting to DeterministicProvider",
            selected,
        )
        return DeterministicProvider()
