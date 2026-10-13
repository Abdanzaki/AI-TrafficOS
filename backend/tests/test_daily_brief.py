"""Tests for Automatic Daily Traffic Briefs (Feature 1).

Validates:
1. Deterministic aggregation of observed incidents and violations across 2 days.
2. Prediction hotspot extraction from real AIPrediction records.
3. Day-over-day trend calculation with honest insufficient history handling.
4. Per-section data provenance ('observed', 'predicted').
5. Empty database behavior producing explicit no-data notes instead of fake zeros.
6. Silent fallback of ?rephrase=true without Gemini API key.
7. RBAC access control and date parameter handling.
"""

from datetime import date, datetime, time, timezone
import uuid
from httpx import AsyncClient
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import engine
from app.models.ai import AIPrediction
from app.models.event import Incident
from app.models.intersection import Intersection
from app.models.violation import Violation


@pytest.fixture(autouse=True)
async def clean_engine_pool():
    """Ensure connection pool is disposed between tests."""
    yield
    await engine.dispose()


@pytest.fixture
async def sample_intersection(db_session: AsyncSession) -> Intersection:
    """Create test intersection for linking incidents and predictions."""
    code = f"BRIEF_{uuid.uuid4().hex[:6].upper()}"
    junction = Intersection(
        name="Brief Test Junction",
        code=code,
        status="active",
        city="Hyderabad",
        zone="West",
        lat=17.4400,
        lon=78.3489,
    )
    db_session.add(junction)
    await db_session.commit()
    await db_session.refresh(junction)
    return junction


@pytest.mark.anyio
async def test_daily_brief_empty_database_explicit_no_data(
    async_client: AsyncClient,
    test_users: dict[str, dict[str, str | int]],
):
    """An empty database or query window with no data produces explicit 'no data' notes, not zeros."""
    token = test_users["analyst"]["token"]
    # Query a distant past date where no seed data exists
    target_date = "2020-01-01"

    resp = await async_client.get(
        f"/api/v1/briefs/daily?date={target_date}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["date"] == target_date
    assert "generated_at" in data

    # Incidents section: explicit no data
    incidents = data["incidents"]
    assert incidents["provenance"] == "observed"
    assert incidents["has_data"] is False
    assert incidents["count"] is None
    assert incidents["total"] is None
    assert incidents["by_severity"] == {}
    assert "No incident data recorded" in incidents["note"]

    # Violations section: explicit no data
    violations = data["violations"]
    assert violations["provenance"] == "observed"
    assert violations["has_data"] is False
    assert violations["count"] is None
    assert violations["total"] is None
    assert violations["by_type"] == {}
    assert "No violation records found" in violations["note"]

    # Hotspots section: explicit no predictions
    hotspots = data["hotspots"]
    assert hotspots["provenance"] == "predicted"
    assert hotspots["has_data"] is False
    assert hotspots["items"] == []
    assert "No forward hotspot predictions available" in hotspots["note"]

    # Trends section: explicit insufficient history
    trends = data["trends"]
    assert trends["provenance"] == "observed"
    assert trends["has_sufficient_history"] is False
    assert trends["incident_delta"] is None
    assert trends["violation_delta"] is None
    assert "Insufficient history" in trends["note"]


@pytest.mark.anyio
async def test_daily_brief_seeded_counts_deltas_and_provenance(
    async_client: AsyncClient,
    db_session: AsyncSession,
    test_users: dict[str, dict[str, str | int]],
    sample_intersection: Intersection,
):
    """Seed incidents and violations on two days and assert counts, deltas, and provenance."""
    from sqlalchemy import delete

    token = test_users["officer"]["token"]

    target_d = date(2028, 8, 15)
    prev_d = date(2028, 8, 14)
    today_d = date(2028, 8, 16)

    # Clean up any potential leftover records from previous test runs
    await db_session.execute(
        delete(Incident).where(
            Incident.created_at >= datetime.combine(prev_d, time.min, tzinfo=timezone.utc),
            Incident.created_at <= datetime.combine(today_d, time.max, tzinfo=timezone.utc),
        )
    )
    await db_session.execute(
        delete(Violation).where(
            Violation.detected_at >= datetime.combine(prev_d, time.min, tzinfo=timezone.utc),
            Violation.detected_at <= datetime.combine(today_d, time.max, tzinfo=timezone.utc),
        )
    )
    await db_session.execute(
        delete(AIPrediction).where(
            AIPrediction.predicted_for >= datetime.combine(today_d, time.min, tzinfo=timezone.utc),
            AIPrediction.predicted_for <= datetime.combine(today_d, time.max, tzinfo=timezone.utc),
        )
    )
    await db_session.commit()

    # 1. Day Before Yesterday (2026-08-14)
    # 1 incident, 2 violations
    dt_prev = datetime.combine(prev_d, time(14, 0), tzinfo=timezone.utc)
    inc_prev = Incident(
        intersection_id=sample_intersection.id,
        severity="low",
        status="reported",
        description="Minor debris on road",
        created_at=dt_prev,
    )
    v_prev1 = Violation(
        intersection_id=sample_intersection.id,
        violation_type="no_helmet",
        confidence=0.95,
        status="recorded",
        detected_at=dt_prev,
    )
    v_prev2 = Violation(
        intersection_id=sample_intersection.id,
        violation_type="no_helmet",
        confidence=0.90,
        status="recorded",
        detected_at=dt_prev,
    )
    db_session.add_all([inc_prev, v_prev1, v_prev2])

    # 2. Yesterday (2026-08-15)
    # 3 incidents: 2 critical, 1 medium
    # 4 violations: 3 red_light, 1 wrong_way
    dt_yest = datetime.combine(target_d, time(10, 30), tzinfo=timezone.utc)
    inc_y1 = Incident(
        intersection_id=sample_intersection.id,
        severity="critical",
        status="reported",
        description="Severe two-vehicle collision",
        created_at=dt_yest,
    )
    inc_y2 = Incident(
        intersection_id=sample_intersection.id,
        severity="critical",
        status="acknowledged",
        description="Overturned commercial carrier",
        created_at=dt_yest,
    )
    inc_y3 = Incident(
        intersection_id=sample_intersection.id,
        severity="medium",
        status="reported",
        description="Disabled bus blocking turn lane",
        created_at=dt_yest,
    )

    v_y1 = Violation(
        intersection_id=sample_intersection.id,
        violation_type="red_light",
        confidence=0.98,
        status="recorded",
        detected_at=dt_yest,
    )
    v_y2 = Violation(
        intersection_id=sample_intersection.id,
        violation_type="red_light",
        confidence=0.96,
        status="recorded",
        detected_at=dt_yest,
    )
    v_y3 = Violation(
        intersection_id=sample_intersection.id,
        violation_type="red_light",
        confidence=0.92,
        status="recorded",
        detected_at=dt_yest,
    )
    v_y4 = Violation(
        intersection_id=sample_intersection.id,
        violation_type="wrong_way",
        confidence=0.88,
        status="recorded",
        detected_at=dt_yest,
    )
    db_session.add_all([inc_y1, inc_y2, inc_y3, v_y1, v_y2, v_y3, v_y4])

    # 3. Today's Forward Hotspot Prediction (2026-08-16)
    dt_today = datetime.combine(today_d, time(9, 0), tzinfo=timezone.utc)
    prediction = AIPrediction(
        intersection_id=sample_intersection.id,
        prediction_type="congestion",
        predicted_for=dt_today,
        payload={"target": "congestion", "value": 84.5, "congestion": 84.5},
        confidence=0.89,
        model_version="forecaster_v1",
    )
    db_session.add(prediction)
    await db_session.commit()

    # Query brief for target_date
    resp = await async_client.get(
        f"/api/v1/briefs/daily?date={target_d.isoformat()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Incidents verification
    incidents = data["incidents"]
    assert incidents["provenance"] == "observed"
    assert incidents["has_data"] is True
    assert incidents["count"] == 3
    assert incidents["total"] == 3
    assert incidents["by_severity"] == {"critical": 2, "medium": 1}

    # Violations verification
    violations = data["violations"]
    assert violations["provenance"] == "observed"
    assert violations["has_data"] is True
    assert violations["count"] == 4
    assert violations["total"] == 4
    assert violations["by_type"] == {"red_light": 3, "wrong_way": 1}

    # Hotspots verification
    hotspots = data["hotspots"]
    assert hotspots["provenance"] == "predicted"
    assert hotspots["has_data"] is True
    assert len(hotspots["items"]) >= 1
    item = hotspots["items"][0]
    assert item["intersection_id"] == sample_intersection.id
    assert item["predicted_congestion"] == 84.5
    assert item["confidence"] == 0.89

    # Day-over-Day Trends verification
    trends = data["trends"]
    assert trends["provenance"] == "observed"
    assert trends["has_sufficient_history"] is True
    # 3 yesterday - 1 day before = +2
    assert trends["incident_delta"] == 2
    # 4 yesterday - 2 day before = +2
    assert trends["violation_delta"] == 2
    assert trends["direction"] == "increased"
    assert "+2 incidents" in trends["note"]
    assert "+2 violations" in trends["note"]

    # Markdown narrative contains facts
    summary = data["summary_text"]
    assert "Daily Traffic Operations Brief" in summary
    assert "**Total Incidents:** 3" in summary
    assert "**Total Violations:** 4" in summary
    assert sample_intersection.name in summary


@pytest.mark.anyio
async def test_daily_brief_rephrase_without_key_falls_back_silently(
    async_client: AsyncClient,
    test_users: dict[str, dict[str, str | int]],
    monkeypatch: pytest.MonkeyPatch,
):
    """Calling ?rephrase=true when GEMINI_API_KEY is not set falls back silently to deterministic text."""
    # Ensure Gemini keys are unset
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("ASSISTANT_LLM_API_KEY", "")

    token = test_users["analyst"]["token"]

    resp = await async_client.get(
        "/api/v1/briefs/daily?rephrase=true&date=2028-08-15",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Rephrased flag is False because fallback was used
    assert data["rephrased"] is False
    assert "Daily Traffic Operations Brief" in data["summary_text"]


@pytest.mark.anyio
async def test_daily_brief_rbac_and_validation(
    async_client: AsyncClient,
    test_users: dict[str, dict[str, str | int]],
):
    """RBAC authentication guards and invalid date validation."""
    # 1. Unauthenticated request rejected with 401
    resp_unauth = await async_client.get("/api/v1/briefs/daily")
    assert resp_unauth.status_code == 401

    # 2. Authenticated analyst, officer, admin all succeed
    for role in ["analyst", "officer", "admin"]:
        tok = test_users[role]["token"]
        resp_auth = await async_client.get(
            "/api/v1/briefs/daily",
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert resp_auth.status_code == 200

    # 3. Malformed date format returns 400
    token = test_users["admin"]["token"]
    resp_bad_date = await async_client.get(
        "/api/v1/briefs/daily?date=not-a-real-date",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_bad_date.status_code == 400
    assert "Invalid date format" in resp_bad_date.json()["detail"]
