"""Assistant error definitions.

Defines domain exceptions including role-based permission denials and
grounded junction resolution errors.
"""

from typing import Any, Optional


class AssistantError(Exception):
    """Base exception for AI Assistant errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class PermissionDeniedError(AssistantError):
    """Raised when the caller's role is not authorized to execute an assistant tool.

    Attributes:
        role: The caller's authenticated role (e.g. 'analyst', 'traffic_officer').
        domain: The domain capability requested (e.g. 'routing_advice', 'simulate_signal_timing').
        message: Human-readable error description.
    """

    def __init__(
        self,
        role: str,
        domain: str,
        message: Optional[str] = None,
    ) -> None:
        self.role = role
        self.domain = domain
        detail = (
            message
            or f"Your role ({role}) doesn't include {domain}. Operator permissions ('traffic_officer' or 'admin') are required."
        )
        super().__init__(detail)


class JunctionResolutionError(AssistantError):
    """Base exception for junction lookup and entity extraction failures."""


class JunctionNotFoundError(JunctionResolutionError):
    """Raised when an explicit junction reference does not exist in the database.

    Attributes:
        identifier: The numeric ID or string name requested.
        suggestions: List of nearby or available real intersections for clarification.
    """

    def __init__(
        self,
        identifier: Any,
        suggestions: Optional[list[dict[str, Any]]] = None,
        message: Optional[str] = None,
    ) -> None:
        self.identifier = identifier
        self.suggestions = suggestions or []
        detail = message or f"Junction {identifier} does not exist in the system."
        super().__init__(detail)


class AmbiguousJunctionError(JunctionResolutionError):
    """Raised when a junction name query matches multiple database records.

    Attributes:
        query_term: The search term that produced ambiguous matches.
        matches: List of candidate intersections matching the query.
    """

    def __init__(
        self,
        query_term: str,
        matches: list[dict[str, Any]],
        message: Optional[str] = None,
    ) -> None:
        self.query_term = query_term
        self.matches = matches
        detail = (
            message
            or f"Multiple intersections match '{query_term}'. Please clarify which intersection you mean."
        )
        super().__init__(detail)
