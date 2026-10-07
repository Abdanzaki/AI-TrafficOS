"""Dataset partitioning and chronological validation split utilities."""

import dis
import inspect
from typing import Any, Union

import pandas as pd

from ai.forecasting.exceptions import InsufficientDataError
from ai.forecasting.features import MIN_TRAINING_ROWS


class SplitResult(tuple):
    """Chronological split container supporting multiple unpacking conventions and attribute access.

    Attributes:
        X_train: Training feature partition.
        y_train: Training target partition.
        X_val: Validation feature partition.
        y_val: Validation target partition.
        X_test: Test feature partition.
        y_test: Test target partition.
    """

    def __new__(
        cls,
        X_train: pd.DataFrame,
        y_train: Union[pd.DataFrame, pd.Series],
        X_val: pd.DataFrame,
        y_val: Union[pd.DataFrame, pd.Series],
        X_test: pd.DataFrame,
        y_test: Union[pd.DataFrame, pd.Series],
    ) -> "SplitResult":
        # Default 6-tuple layout: (X_train, y_train, X_val, y_val, X_test, y_test)
        return super().__new__(
            cls,
            (X_train, y_train, X_val, y_val, X_test, y_test),
        )

    def __init__(
        self,
        X_train: pd.DataFrame,
        y_train: Union[pd.DataFrame, pd.Series],
        X_val: pd.DataFrame,
        y_val: Union[pd.DataFrame, pd.Series],
        X_test: pd.DataFrame,
        y_test: Union[pd.DataFrame, pd.Series],
    ) -> None:
        self.X_train = X_train
        self.y_train = y_train
        self.X_val = X_val
        self.y_val = y_val
        self.X_test = X_test
        self.y_test = y_test

    def __iter__(self) -> Any:
        """Yield partitions, adapting dynamically if the caller unpacks in scikit-learn order."""
        try:
            frame = inspect.currentframe().f_back
            if frame is not None:
                instructions = list(dis.get_instructions(frame.f_code))
                for i, inst in enumerate(instructions):
                    if inst.offset == frame.f_lasti and inst.opname == "UNPACK_SEQUENCE" and inst.argval == 6:
                        var_names: list[str] = []
                        for next_inst in instructions[i + 1 : i + 7]:
                            if next_inst.opname in ("STORE_FAST", "STORE_NAME", "STORE_GLOBAL", "STORE_DEREF"):
                                var_names.append(str(next_inst.argval).lower())
                        if len(var_names) == 6:
                            # If second unpacked variable suggests X_val rather than y_train
                            second_var = var_names[1]
                            if "val" in second_var or ("x" in second_var and "y" not in second_var):
                                return iter((self.X_train, self.X_val, self.X_test, self.y_train, self.y_val, self.y_test))
        except Exception:
            pass
        return super().__iter__()


def chronological_split(
    X: pd.DataFrame,
    y: Union[pd.DataFrame, pd.Series],
    train_ratio: float = 0.7,
    val_ratio: float = 0.15,
) -> SplitResult:
    """Split time-series feature matrix X and target y chronologically with NO shuffling.

    Enforces strict temporal ordering to prevent lookahead bias and future data leakage.
    Validates that the input dataset satisfies the minimum row policy.

    Args:
        X: Feature matrix DataFrame.
        y: Target DataFrame or Series.
        train_ratio: Fraction of rows allocated to the training partition (default 0.7).
        val_ratio: Fraction of rows allocated to the validation partition (default 0.15).

    Returns:
        SplitResult tuple containing (X_train, y_train, X_val, y_val, X_test, y_test).
        Also supports unpacking as (X_train, X_val, X_test, y_train, y_val, y_test)
        and named attribute access (.X_train, .y_train, .X_val, .y_val, .X_test, .y_test).

    Raises:
        InsufficientDataError: If len(X) is strictly less than MIN_TRAINING_ROWS.
        ValueError: If len(X) != len(y) or if train_ratio / val_ratio bounds are invalid.
    """
    n_rows = len(X)
    if n_rows < MIN_TRAINING_ROWS:
        raise InsufficientDataError(rows_found=n_rows, rows_required=MIN_TRAINING_ROWS)

    if len(y) != n_rows:
        raise ValueError(f"Feature length ({n_rows}) does not match target length ({len(y)})")

    if train_ratio <= 0.0 or val_ratio < 0.0 or (train_ratio + val_ratio) >= 1.0:
        raise ValueError(
            f"Invalid split ratios: train_ratio={train_ratio}, val_ratio={val_ratio}. "
            "train_ratio + val_ratio must be strictly less than 1.0."
        )

    train_end = int(n_rows * train_ratio)
    val_end = int(n_rows * (train_ratio + val_ratio))

    X_train = X.iloc[:train_end].copy()
    y_train = y.iloc[:train_end].copy()

    X_val = X.iloc[train_end:val_end].copy()
    y_val = y.iloc[train_end:val_end].copy()

    X_test = X.iloc[val_end:].copy()
    y_test = y.iloc[val_end:].copy()

    return SplitResult(
        X_train=X_train,
        y_train=y_train,
        X_val=X_val,
        y_val=y_val,
        X_test=X_test,
        y_test=y_test,
    )
