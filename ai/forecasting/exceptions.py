"""Exceptions for traffic forecasting and time-series feature engineering."""

from typing import Optional


class InsufficientDataError(Exception):
    """Raised when telemetry or feature dataset contains fewer rows than required for forecasting.

    Attributes:
        rows_found: The number of telemetry records found in the input dataset.
        rows_required: The minimum number of records required by the policy.
    """

    def __init__(
        self,
        rows_found: int,
        rows_required: int,
        message: Optional[str] = None,
    ) -> None:
        self.rows_found: int = int(rows_found)
        self.rows_required: int = int(rows_required)
        if message is None:
            message = (
                f"Insufficient telemetry data for forecasting model: found {self.rows_found} rows, "
                f"but a minimum of {self.rows_required} rows is required."
            )
        super().__init__(message)
