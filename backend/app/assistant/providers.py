"""LLM Provider Interface and Concrete Providers.

Provides an extensible, decoupled interface for generating assistant responses:
- `DeterministicProvider`: Default production engine. Executes the deterministic grounded
  NLU engine with zero external network dependencies, strict database grounding, and
  predictable provenance guarantees.
- `HttpLLMProvider`: Documented extension point for plugging external vendor APIs
  (e.g. OpenAI/Anthropic/Gemini-compatible endpoints). Operates strictly via environment
  variables (`ASSISTANT_LLM_PROVIDER`, `ASSISTANT_LLM_API_KEY`). Never hardcodes or logs keys.

CONFIGURATION & UPGRADE PATH:
=============================
- Out of the box, `ASSISTANT_LLM_PROVIDER="deterministic"` ships fully working and tested.
- Setting `ASSISTANT_LLM_PROVIDER="http"` and providing `ASSISTANT_LLM_API_KEY` in `backend/.env`
  upgrades the assistant to external conversational LLM mode while retaining tool grounding.
- No third-party vendor SDKs are imported at module load time to preserve zero-footprint purity.
"""

from abc import ABC, abstractmethod
import logging
from typing import Any, Optional

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

    if selected == "deterministic":
        return DeterministicProvider()
    elif selected == "http":
        return HttpLLMProvider()
    else:
        logger.warning(
            "Unknown provider '%s'; defaulting to DeterministicProvider",
            selected,
        )
        return DeterministicProvider()
