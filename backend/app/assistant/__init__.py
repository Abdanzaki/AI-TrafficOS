"""AI TrafficOS Assistant Package (Phase 9 Stage 4).

ARCHITECTURE OVERVIEW:
======================
The assistant package provides a grounded, deterministic conversational interface for municipal
traffic operators and analysts. It bridges natural language queries to live database services,
simulation engines, and predictive forecasting pipelines without data fabrication.

Package Components:
1. `tools.py`: Domain tools layer. Exactly one asynchronous typed tool per domain.
   Enforces strict per-domain role permissions and attaches provenance metadata
   ('observed', 'predicted', 'recommended') and confidence metrics to every datum.
2. `nlu.py`: Deterministic Natural Language Understanding engine. Classifies queries across
   10 domain intents (ordered by specificity), resolves physical intersection entities against
   the database, dispatches tool executions, and generates structured templates with clear
   provenance separation.
3. `providers.py`: Decoupled LLM provider interface (`LLMProvider`). Defaults to
   `DeterministicProvider` (zero network footprint, zero external API keys). Provides a clean
   extension point (`HttpLLMProvider`) for external LLMs via environment variables.
4. `errors.py`: Domain-specific exceptions including `PermissionDeniedError`,
   `JunctionNotFoundError`, and `AmbiguousJunctionError`.

ROLE-BASED ACCESS CONTROL (RBAC) MATRIX:
=========================================
Tool                      | Allowed Roles                | Rationale
--------------------------|------------------------------|---------------------------------------------
get_traffic_state         | admin, traffic_officer, analyst | Read-only observed sensor/perception records
get_congestion_ranking    | admin, traffic_officer, analyst | Read-only ranking of congested intersections
get_predictions_30min     | admin, traffic_officer, analyst | Read-only forward forecasting outputs
get_incidents             | admin, traffic_officer, analyst | Read-only traffic incidents & hazard alerts
get_junction_history      | admin, traffic_officer, analyst | Read-only multi-source junction telemetry
get_signal_status         | admin, traffic_officer, analyst | Read-only signal controller hardware & phases
get_control_decisions     | admin, traffic_officer, analyst | Read-only AI supervisory decision explanations
get_analytics_summary     | admin, traffic_officer, analyst | Read-only network aggregated statistics
get_emergency_events      | admin, traffic_officer, analyst | Read-only active emergency transit events
get_routing_advice        | admin, traffic_officer       | Operational dispatch & dynamic routing
simulate_signal_timing    | admin, traffic_officer       | Operational supervisory what-if simulation

PROVIDER CONFIGURATION:
=======================
Configuration is driven strictly via environment variables:
- `ASSISTANT_LLM_PROVIDER`: 'deterministic' (default) or 'http'.
- `ASSISTANT_LLM_API_KEY`: API key for external provider (never logged, never committed).
The deterministic engine ships fully working out of the box with zero third-party dependencies.
"""

from app.assistant.errors import (
    AmbiguousJunctionError,
    AssistantError,
    JunctionNotFoundError,
    JunctionResolutionError,
    PermissionDeniedError,
)
from app.assistant.nlu import (
    DeterministicNLUEngine,
    NLUResult,
    extract_numeric_junction_id,
    extract_route_endpoints,
    extract_whatif_parameters,
    resolve_junction_carryover,
    resolve_junction_reference,
)
from app.assistant.providers import (
    DeterministicProvider,
    HttpLLMProvider,
    LLMProvider,
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

__all__ = [
    # Errors
    "AssistantError",
    "PermissionDeniedError",
    "JunctionResolutionError",
    "JunctionNotFoundError",
    "AmbiguousJunctionError",
    # Tools
    "get_traffic_state",
    "get_congestion_ranking",
    "get_predictions_30min",
    "get_routing_advice",
    "get_incidents",
    "get_junction_history",
    "get_signal_status",
    "get_control_decisions",
    "get_analytics_summary",
    "get_emergency_events",
    "simulate_signal_timing",
    # NLU
    "DeterministicNLUEngine",
    "NLUResult",
    "resolve_junction_reference",
    "extract_numeric_junction_id",
    "extract_route_endpoints",
    "extract_whatif_parameters",
    "resolve_junction_carryover",
    # Providers
    "LLMProvider",
    "DeterministicProvider",
    "HttpLLMProvider",
    "get_llm_provider",
]
