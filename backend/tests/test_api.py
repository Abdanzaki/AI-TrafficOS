"""Phase 1 Backend and Architecture Test Suite.

Tests API v1 health and version endpoints, WebSocket handshake,
configuration defaults, database models, and AI stub contracts.
"""

import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Ensure backend and repo root are in python path
BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.api.v1.router import APP_VERSION, router as v1_router
from app.api.v1.websocket import router as ws_router
from app.core.config import settings
from app.core.database import Base
from app.main import create_app
from app.models import Incident, Intersection, SignalPhase, VehicleEvent


@pytest.fixture
def client() -> TestClient:
    """Fixture providing a TestClient configured with create_app()."""
    app = create_app()
    return TestClient(app)


def test_health_endpoint(client: TestClient) -> None:
    """GET /api/v1/health must return exact status, service, and version."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    expected = {
        "status": "ok",
        "service": "ai-trafficos",
        "version": APP_VERSION,
    }
    assert response.json() == expected
    assert APP_VERSION == "0.1.0"


def test_version_endpoint(client: TestClient) -> None:
    """GET /api/v1/version must return service and version."""
    response = client.get("/api/v1/version")
    assert response.status_code == 200
    expected = {
        "service": "ai-trafficos",
        "version": APP_VERSION,
    }
    assert response.json() == expected


def test_websocket_handshake(client: TestClient) -> None:
    """WebSocket at /api/v1/ws must send single handshake and close politely."""
    with client.websocket_connect("/api/v1/ws") as websocket:
        payload = websocket.receive_json()
        assert payload == {
            "type": "handshake",
            "status": "connected",
            "note": "Phase 1: no live traffic streams yet",
        }
        # Connection should close politely with code 1000
        # In testclient, subsequent receive raises WebSocketDisconnect with code 1000
        with pytest.raises(Exception) as excinfo:
            websocket.receive_json()
        # Ensure code is 1000 if disconnect exception
        if hasattr(excinfo.value, "code"):
            assert excinfo.value.code == 1000


def test_settings_defaults() -> None:
    """Verify settings defaults conform to Phase 1 requirements."""
    assert "postgresql+asyncpg://" in settings.DATABASE_URL
    assert settings.REDIS_URL == "redis://localhost:6379/0"
    assert settings.ENV == "development"
    assert "http://localhost:3000" in settings.CORS_ORIGINS


def test_models_metadata() -> None:
    """Verify all 4 required tables are registered in Base.metadata."""
    table_names = set(Base.metadata.tables.keys())
    expected_tables = {
        "intersections",
        "signal_phases",
        "vehicle_events",
        "incidents",
    }
    assert expected_tables.issubset(table_names)

    # Check columns
    intersections_cols = Base.metadata.tables["intersections"].columns
    assert "id" in intersections_cols
    assert "name" in intersections_cols
    assert "lat" in intersections_cols
    assert "lon" in intersections_cols
    assert "created_at" in intersections_cols

    signal_cols = Base.metadata.tables["signal_phases"].columns
    assert "id" in signal_cols
    assert "intersection_id" in signal_cols
    assert "name" in signal_cols
    assert "created_at" in signal_cols

    vehicle_cols = Base.metadata.tables["vehicle_events"].columns
    assert "id" in vehicle_cols
    assert "intersection_id" in vehicle_cols
    assert "event_type" in vehicle_cols
    assert "confidence" in vehicle_cols
    assert "created_at" in vehicle_cols

    incident_cols = Base.metadata.tables["incidents"].columns
    assert "id" in incident_cols
    assert "intersection_id" in incident_cols
    assert "severity" in incident_cols
    assert "description" in incident_cols
    assert "created_at" in incident_cols


def test_ai_stubs() -> None:
    """Verify AI stubs raise NotImplementedError with exact phase notices."""
    from ai.cv.detectors import BaseDetector
    from ai.prediction.base import BasePredictor
    from ai.common.schemas import Detection, TrafficSnapshot

    # Detection dataclass container
    det = Detection(label="car", confidence=0.95)
    assert det.label == "car"
    assert det.confidence == 0.95

    # TrafficSnapshot dataclass container
    snap = TrafficSnapshot(intersection_id=1, vehicle_count=42)
    assert snap.intersection_id == 1
    assert snap.vehicle_count == 42

    class TestDetector(BaseDetector):
        def detect(self, frame):
            return super().detect(frame)

    class TestPredictor(BasePredictor):
        def predict(self, *args, **kwargs):
            return super().predict(*args, **kwargs)

    detector = TestDetector()
    with pytest.raises(NotImplementedError) as exc_det:
        detector.detect(None)
    assert "Phase 4 will provide concrete detectors" in str(exc_det.value)

    predictor = TestPredictor()
    with pytest.raises(NotImplementedError) as exc_pred:
        predictor.predict()
    assert "Phase 5 will provide flow forecasting predictors" in str(exc_pred.value)
