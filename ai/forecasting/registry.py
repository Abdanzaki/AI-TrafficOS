"""Model registry and artifact versioning for traffic forecasting."""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Optional, Union

import numpy as np
import pandas as pd

from ai.forecasting.models import TrafficForecaster

DEFAULT_ARTIFACTS_DIR: Path = Path(__file__).resolve().parent / "artifacts"


def _sanitize_for_json(data: Any) -> Any:
    """Recursively convert numpy, pandas, and datetime objects into JSON-compliant primitives."""
    if isinstance(data, dict):
        return {str(k): _sanitize_for_json(v) for k, v in data.items()}
    if isinstance(data, (list, tuple, set)):
        return [_sanitize_for_json(item) for item in data]
    if isinstance(data, (np.integer,)):
        return int(data)
    if isinstance(data, (np.floating, float)):
        return float(data) if not np.isnan(data) else None
    if isinstance(data, (np.bool_, bool)):
        return bool(data)
    if isinstance(data, np.ndarray):
        return _sanitize_for_json(data.tolist())
    if isinstance(data, (pd.Timestamp, datetime)):
        return data.isoformat()
    if pd.isna(data):
        return None
    return data


class ModelRegistry:
    """Filesystem-based model registry managing versioned forecasting artifacts."""

    def __init__(self, root: Optional[Union[Path, str]] = None) -> None:
        """Initialize registry under the designated root directory.

        Args:
            root: Base artifacts directory. Defaults to 'ai/forecasting/artifacts'.
        """
        if root is None:
            self.root: Path = DEFAULT_ARTIFACTS_DIR
        else:
            self.root = Path(root).resolve()

    def _get_existing_versions(self) -> list[int]:
        """Scan directory and return sorted integer version identifiers."""
        if not self.root.exists() or not self.root.is_dir():
            return []

        versions: list[int] = []
        for entry in self.root.iterdir():
            if entry.is_dir():
                match = re.match(r"^v(\d+)$", entry.name)
                if match:
                    versions.append(int(match.group(1)))

        return sorted(versions)

    def register(
        self,
        model: TrafficForecaster,
        metrics: dict[str, Any],
        data_summary: dict[str, Any],
        notes: str = "",
    ) -> str:
        """Register and persist a trained model with evaluation metrics and training provenance.

        Never overwrites previous artifacts. Creates a new artifacts/vN/ subdirectory
        with model.joblib and metadata.json.

        Args:
            model: Trained TrafficForecaster instance.
            metrics: Multi-target validation and test evaluation metrics dictionary.
            data_summary: Provenance summary of training dataset.
            notes: Optional human-readable description or experiment notes.

        Returns:
            The assigned version string (e.g., 'v1', 'v2').
        """
        self.root.mkdir(parents=True, exist_ok=True)
        existing_versions = self._get_existing_versions()
        next_ver_int = (existing_versions[-1] + 1) if existing_versions else 1
        version_str = f"v{next_ver_int}"

        version_dir = self.root / version_str
        version_dir.mkdir(parents=True, exist_ok=False)

        # 1. Persist model binary
        model_file = version_dir / "model.joblib"
        model.save(model_file)

        # 2. Extract horizon metadata
        horizon_info = {
            "steps": model.meta.get("horizon_steps", 6),
            "step_minutes": model.meta.get("step_minutes", 5),
            "duration_minutes": (
                model.meta.get("horizon_steps", 6) * model.meta.get("step_minutes", 5)
            ),
        }

        # 3. Build metadata dictionary
        metadata: dict[str, Any] = {
            "version": version_str,
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "metrics": _sanitize_for_json(metrics),
            "data_summary": _sanitize_for_json(data_summary),
            "feature_names": list(model.feature_names),
            "target_names": list(model.target_names),
            "horizon": horizon_info,
            "horizon_info": horizon_info,
            "notes": str(notes),
        }

        meta_file = version_dir / "metadata.json"
        meta_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        return version_str

    def get_version(self, v: Union[str, int]) -> tuple[TrafficForecaster, dict[str, Any]]:
        """Retrieve a specific model version and its associated metadata.

        Args:
            v: Version string (e.g. 'v1') or integer version index (e.g. 1).

        Returns:
            tuple (model, metadata) where model is TrafficForecaster and metadata is a dict.

        Raises:
            FileNotFoundError: If the requested version directory or files do not exist.
        """
        v_str = f"v{v}" if not str(v).startswith("v") else str(v)
        version_dir = self.root / v_str

        if not version_dir.exists() or not version_dir.is_dir():
            raise FileNotFoundError(
                f"Model version '{v_str}' not found in registry at {self.root}"
            )

        model_path = version_dir / "model.joblib"
        meta_path = version_dir / "metadata.json"

        if not model_path.exists():
            raise FileNotFoundError(
                f"Model file missing for version '{v_str}' at {model_path}"
            )
        if not meta_path.exists():
            raise FileNotFoundError(
                f"Metadata file missing for version '{v_str}' at {meta_path}"
            )

        model = TrafficForecaster.load(model_path)
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))

        return model, metadata

    def get_latest(self) -> tuple[TrafficForecaster, dict[str, Any]]:
        """Retrieve the latest registered model and its metadata.

        Returns:
            tuple (model, metadata) for the highest version index.

        Raises:
            FileNotFoundError: If no models are registered in this registry.
        """
        versions = self._get_existing_versions()
        if not versions:
            raise FileNotFoundError(
                f"No forecasting models registered in registry at {self.root}"
            )

        latest_version_str = f"v{versions[-1]}"
        return self.get_version(latest_version_str)

    def list_versions(self) -> list[dict[str, Any]]:
        """List metadata for all registered models sorted chronologically by version number.

        Returns:
            List of metadata dictionaries sorted ascending by version index.
        """
        versions = self._get_existing_versions()
        results: list[dict[str, Any]] = []

        for v_num in versions:
            version_str = f"v{v_num}"
            meta_path = self.root / version_str / "metadata.json"
            if meta_path.exists():
                try:
                    data = json.loads(meta_path.read_text(encoding="utf-8"))
                    results.append(data)
                except Exception:
                    pass

        return sorted(
            results,
            key=lambda m: int(re.sub(r"[^\d]", "", str(m.get("version", "0"))) or 0),
        )
