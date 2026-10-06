"""Predictive traffic analytics interfaces and base models.

Future predictor implementations (Phase 5):
- Traffic flow forecasting (short-term 5-30 minute lane volume projection)
- Congestion prediction (bottleneck formation and queue dissipation modeling)
"""

from abc import ABC, abstractmethod
from typing import Any


class BasePredictor(ABC):
    """Abstract base class for traffic flow and congestion forecasting models."""

    @abstractmethod
    def predict(self, *args: Any, **kwargs: Any) -> Any:
        """Execute predictive inference over historical or streaming traffic telemetry.

        Args:
            *args: Input feature arrays, historical time-series, or state snapshots.
            **kwargs: Horizon, confidence intervals, or spatial parameters.

        Returns:
            Forecasting output dictionary or prediction structure.

        Raises:
            NotImplementedError: Raised in Phase 1 stubs.
        """
        raise NotImplementedError("Not implemented: Phase 5 will provide flow forecasting predictors")
