"""Exceptions for traffic control services."""

from typing import Optional


class StaleTelemetryError(Exception):
    """Raised when traffic telemetry is older than the allowed freshness threshold or absent.

    Attributes:
        intersection_id: The identifier of the intersection lacking fresh telemetry.
        age_s: The observed telemetry age in seconds (or None if no records exist).
        max_telemetry_age_s: The maximum permissible age threshold.
        message: Human-readable diagnostic explanation.
    """

    def __init__(
        self,
        intersection_id: int,
        age_s: Optional[float] = None,
        max_telemetry_age_s: float = 300.0,
        message: Optional[str] = None,
    ) -> None:
        self.intersection_id = intersection_id
        self.age_s = age_s
        self.age = age_s
        self.telemetry_age_s = age_s
        self.max_telemetry_age_s = max_telemetry_age_s
        if message is None:
            if age_s is None:
                message = (
                    f"No telemetry records found for intersection {intersection_id}."
                )
            else:
                message = (
                    f"Telemetry for intersection {intersection_id} is stale: "
                    f"age {age_s:.1f}s exceeds threshold {max_telemetry_age_s:.1f}s."
                )
        self.message = message
        super().__init__(message)


class InsufficientDataError(Exception):
    """Raised when insufficient telemetry or context is available to evaluate control decisions."""

    def __init__(
        self, message: str = "Insufficient data to evaluate traffic control decision."
    ) -> None:
        self.message = message
        super().__init__(message)


class UnsafeStateError(Exception):
    """Raised when an operation would lead to an unsafe traffic control state."""

    def __init__(
        self, message: str = "Unsafe traffic control state encountered or requested."
    ) -> None:
        self.message = message
        super().__init__(message)
