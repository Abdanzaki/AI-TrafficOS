"""Integration tests for crash candidate backend bridge and alert pipeline.

Covers:
1. `handle_crash_candidate` persists Incident row with correct severity:
   - 'high' for 'likely' verdict
   - 'medium' for 'possible' verdict
   - Status 'reported', description explicitly names verdict and confidence
2. Evidence snapshot frame persistence via `save_evidence_snapshot`
3. Real-time EventBus envelope publishing:
   - event_type == 'incident.created'
   - source == 'crash-detector'
   - Payload contains: incident_id, intersection_id, timestamp, confidence, verdict, evidence_ref
   - No raw image bytes or secrets in payload
4. End-to-end notification routing via `maybe_notify_for_event`:
   - 'likely' (high severity) escalates to notification severity 'error' with 'Crash Alert' title
   - 'possible' (medium severity) routes to notification severity 'warning' with 'Crash Alert' title
5. REST API filtering via `GET /api/v1/incidents?is_crash=true`
"""

from datetime import datetime, timezone
import os
from pathlib import Path
from unittest.mock import AsyncMock
import uuid
from httpx import AsyncClient
import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ai.cv.crash import CrashCandidate
from app.core.database import engine
from app.models.event import Incident
from app.models.intersection import Intersection
from app.realtime import INCIDENT_CREATED, EventEnvelope, maybe_notify_for_event
from app.vision.crash import handle_crash_candidate
from app.vision.storage import save_evidence_snapshot


@pytest.fixture(autouse=True)
async def dispose_engine():
    yield
    await engine.dispose()


@pytest.fixture
async def sample_intersection(db_session: AsyncSession) -> Intersection:
    """Provision a test intersection."""
    code = f"CRASH_JNC_{uuid.uuid4().hex[:6].upper()}"
    junction = Intersection(
        name="Collision Test Junction",
        code=code,
        status="active",
        city="Bengaluru",
        zone="Tech Corridor",
        lat=12.9716,
        lon=77.5946,
    )
    db_session.add(junction)
    await db_session.commit()
    await db_session.refresh(junction)
    return junction


# ==============================================================================
# 1. handle_crash_candidate: likely -> high severity + EventBus publish
# ==============================================================================

@pytest.mark.anyio
async def test_handle_crash_candidate_likely_persists_high_severity(
    db_session: AsyncSession,
    sample_intersection: Intersection,
):
    """'likely' crash candidate persists Incident with severity 'high' and emits real-time alert."""
    now = datetime(2026, 10, 13, 14, 30, 0, tzinfo=timezone.utc)
    candidate = CrashCandidate(
        involved_track_ids=[11, 12],
        timestamp=now,
        confidence=0.88,
        verdict="likely",
        junction_id=sample_intersection.id,
        camera_id="cam_east_01",
        location=(150.0, 120.0),
        signals_fired=["multi_vehicle_stop_cluster", "abrupt_deceleration", "trajectory_convergence"],
        details={"vehicle_count": 2},
    )

    mock_bus = AsyncMock()
    mock_bus.publish = AsyncMock()

    incident = await handle_crash_candidate(
        db=db_session,
        candidate=candidate,
        intersection_id=sample_intersection.id,
        bus=mock_bus,
    )
    await db_session.commit()

    # 1. Assert Incident row in database
    assert incident.id is not None
    assert incident.intersection_id == sample_intersection.id
    assert incident.severity == "high", "Likely crash candidate must produce severity 'high'"
    assert incident.status == "reported"
    assert "Likely crash detected (confidence 0.88):" in incident.description
    assert "tracks [11, 12]" in incident.description
    assert "multi_vehicle_stop_cluster" in incident.description
    assert incident.reported_by is None  # Automated perception

    # 2. Assert EventBus publish
    mock_bus.publish.assert_awaited_once()
    call_args = mock_bus.publish.call_args
    event_type = call_args.kwargs.get("event_type") or call_args.args[0]
    payload = call_args.kwargs.get("payload") or call_args.args[1]
    source = call_args.kwargs.get("source") or (call_args.args[2] if len(call_args.args) > 2 else None)

    assert event_type == INCIDENT_CREATED
    assert source == "crash-detector"
    assert payload["incident_id"] == incident.id
    assert payload["intersection_id"] == sample_intersection.id
    assert payload["severity"] == "high"
    assert payload["verdict"] == "likely"
    assert payload["confidence"] == 0.88
    assert payload["involved_track_ids"] == [11, 12]
    assert payload["camera_id"] == "cam_east_01"

    # Verify payload has NO raw image bytes or passwords/secrets
    for k, v in payload.items():
        assert not isinstance(v, (bytes, bytearray)), f"Field {k} contains raw bytes!"
        assert "password" not in k.lower() and "secret" not in k.lower()


# ==============================================================================
# 2. handle_crash_candidate: possible -> medium severity
# ==============================================================================

@pytest.mark.anyio
async def test_handle_crash_candidate_possible_persists_medium_severity(
    db_session: AsyncSession,
    sample_intersection: Intersection,
):
    """'possible' crash candidate persists Incident with severity 'medium'."""
    now = datetime(2026, 10, 13, 14, 35, 0, tzinfo=timezone.utc)
    candidate = CrashCandidate(
        involved_track_ids=[5],
        timestamp=now,
        confidence=0.58,
        verdict="possible",
        junction_id=sample_intersection.id,
        camera_id="cam_south_02",
        location=(80.0, 90.0),
        signals_fired=["abrupt_deceleration"],
        details={"vehicle_count": 1},
    )

    mock_bus = AsyncMock()

    incident = await handle_crash_candidate(
        db=db_session,
        candidate=candidate,
        bus=mock_bus,
    )
    await db_session.commit()

    assert incident.id is not None
    assert incident.severity == "medium", "Possible crash candidate must produce severity 'medium'"
    assert incident.status == "reported"
    assert "Possible crash detected (confidence 0.58) — unverified:" in incident.description
    assert "tracks [5]" in incident.description

    # Assert envelope payload reflects possible verdict
    call_args = mock_bus.publish.call_args
    payload = call_args.kwargs.get("payload") or call_args.args[1]
    assert payload["verdict"] == "possible"
    assert payload["severity"] == "medium"
    assert payload["confidence"] == 0.58


# ==============================================================================
# 3. Evidence snapshot storage integration
# ==============================================================================

@pytest.mark.anyio
async def test_handle_crash_candidate_saves_evidence_snapshot(
    db_session: AsyncSession,
    sample_intersection: Intersection,
    tmp_path: Path,
):
    """Providing a BGR frame writes snapshot to disk and stores reference in Incident and payload."""
    test_frame = np.full((120, 160, 3), 128, dtype=np.uint8)
    now = datetime(2026, 10, 13, 14, 40, 0, tzinfo=timezone.utc)

    # Test direct save_evidence_snapshot first
    snapshot_path = save_evidence_snapshot(
        frame_bgr=test_frame,
        category="crash_test",
        timestamp=now,
        output_dir=tmp_path,
    )
    assert snapshot_path is not None
    assert os.path.exists(snapshot_path)
    assert snapshot_path.endswith(".jpg")

    # Test via handle_crash_candidate
    candidate = CrashCandidate(
        involved_track_ids=[20, 21],
        timestamp=now,
        confidence=0.82,
        verdict="likely",
        junction_id=sample_intersection.id,
        evidence_ref=snapshot_path,
    )

    mock_bus = AsyncMock()
    incident = await handle_crash_candidate(
        db=db_session,
        candidate=candidate,
        bus=mock_bus,
    )
    await db_session.commit()

    assert snapshot_path in incident.description
    payload = mock_bus.publish.call_args.kwargs.get("payload") or mock_bus.publish.call_args.args[1]
    assert payload["evidence_ref"] == snapshot_path


# ==============================================================================
# 4. End-to-end notification routing (notify.py)
# ==============================================================================

@pytest.mark.anyio
async def test_crash_realtime_notification_pipeline(db_session: AsyncSession):
    """`incident.created` for crash candidate correctly formats control-room notifications."""
    inc_id_1 = 880000 + int(uuid.uuid4().int % 10000)
    inc_id_2 = 890000 + int(uuid.uuid4().int % 10000)

    # 1. High severity (likely crash) -> Escalated to 'error' notification
    likely_envelope = EventEnvelope(
        type=INCIDENT_CREATED,
        source="crash-detector",
        payload={
            "incident_id": inc_id_1,
            "intersection_id": 10,
            "severity": "high",
            "status": "reported",
            "confidence": 0.85,
            "verdict": "likely",
            "evidence_ref": "storage/evidence/crash/likely_01.jpg",
        },
    )

    notif_likely = await maybe_notify_for_event(likely_envelope, db=db_session)
    assert notif_likely is not None
    assert notif_likely.severity == "error"
    assert f"Crash Alert #{inc_id_1} (LIKELY)" in notif_likely.title
    assert f"Crash detected #{inc_id_1} [LIKELY]" in notif_likely.message
    assert notif_likely.entity_type == "incident"
    assert notif_likely.entity_id == inc_id_1

    # 2. Medium severity (possible crash) -> 'warning' notification
    possible_envelope = EventEnvelope(
        type=INCIDENT_CREATED,
        source="crash-detector",
        payload={
            "incident_id": inc_id_2,
            "intersection_id": 10,
            "severity": "medium",
            "status": "reported",
            "confidence": 0.61,
            "verdict": "possible",
            "evidence_ref": None,
        },
    )

    notif_possible = await maybe_notify_for_event(possible_envelope, db=db_session)
    assert notif_possible is not None
    assert notif_possible.severity == "warning"
    assert f"Crash Alert #{inc_id_2} (POSSIBLE)" in notif_possible.title
    assert f"Crash detected #{inc_id_2} [POSSIBLE]" in notif_possible.message


# ==============================================================================
# 5. REST API listing and is_crash query filter
# ==============================================================================

@pytest.mark.anyio
async def test_incidents_api_filter_by_crash(
    async_client: AsyncClient,
    test_users: dict[str, dict[str, str | int]],
    db_session: AsyncSession,
    sample_intersection: Intersection,
):
    """GET /api/v1/incidents?is_crash=true returns only crash-detected incidents."""
    admin_token = test_users["admin"]["token"]
    headers = {"Authorization": f"Bearer {admin_token}"}

    uid = uuid.uuid4().hex[:6]
    # Insert 1 crash incident
    crash_inc = Incident(
        intersection_id=sample_intersection.id,
        severity="high",
        status="reported",
        description=f"Likely crash detected (confidence 0.85): tracks [1, 2] tag_{uid}",
        created_at=datetime.now(timezone.utc),
    )
    # Insert 1 non-crash incident
    normal_inc = Incident(
        intersection_id=sample_intersection.id,
        severity="low",
        status="reported",
        description=f"Pothole hazard on road shoulder tag_{uid}",
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(crash_inc)
    db_session.add(normal_inc)
    await db_session.commit()
    await db_session.refresh(crash_inc)
    await db_session.refresh(normal_inc)

    # Filter with is_crash=true
    resp_crash = await async_client.get(
        "/api/v1/incidents",
        params={"is_crash": "true", "search": uid},
        headers=headers,
    )
    assert resp_crash.status_code == 200
    data_crash = resp_crash.json()
    items_crash = data_crash["items"]
    assert any(i["id"] == crash_inc.id for i in items_crash)
    assert not any(i["id"] == normal_inc.id for i in items_crash)

    # Filter with is_crash=false
    resp_non_crash = await async_client.get(
        "/api/v1/incidents",
        params={"is_crash": "false", "search": uid},
        headers=headers,
    )
    assert resp_non_crash.status_code == 200
    data_non_crash = resp_non_crash.json()
    items_non_crash = data_non_crash["items"]
    assert not any(i["id"] == crash_inc.id for i in items_non_crash)
    assert any(i["id"] == normal_inc.id for i in items_non_crash)
