#!/usr/bin/env python3
"""Seed clearly-labeled DEMO traffic data for AI TrafficOS dashboards.

The production database has no live sensors connected, so every data page
renders empty. This script inserts a realistic 24-hour sample dataset for
Hyderabad intersections so dashboards, maps, predictions, and incident pages
come alive for demo / portfolio purposes.

Part 1 (already run in production): 10 intersections, 2,880 traffic records,
12 violations, 3 crash incidents.
Part 2 (this extension): signals + phases, AI predictions (LSTM-style),
AI decisions (control + advisories), notifications, emergency events,
roads/corridors, audit log entries.

HONESTY CONTRACT: every generated row is explicitly labeled as demo/sample:
  - TrafficRecord.source = "demo"
  - Violation.details contains {"demo": True, ...} with a [DEMO] note
  - Incident.description is prefixed with "[DEMO]"
  - Signal.code uses the "DEMO-" prefix; SignalPhase.name is [DEMO]-prefixed
  - AIPrediction.payload contains {"demo": True}; model_version="demo-lstm-v1"
  - AIDecision.rationale is prefixed with "[DEMO]"; payload has demo=True
  - Notification.title/message are prefixed with "[DEMO]"
  - EmergencyEvent rows link only to [DEMO] incidents (no free-text field)
  - Road.name is prefixed with "[DEMO]"
  - AuditLog.details contains {"demo": True}
No generated row is ever presented as a real sensor reading or detection.

Usage:
    DATABASE_URL="postgresql://..." python scripts/seed_demo_data.py

Run from the repository root. Requires DATABASE_URL in the environment.
Idempotent per section: each section is skipped if its demo rows already exist.
"""

import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure backend directory is on sys.path for `app` imports (same pattern as
# scripts/create_admin.py).
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print(
        "ERROR: DATABASE_URL environment variable is not set.\n"
        "Set it to your database connection string and re-run, e.g.:\n"
        '  DATABASE_URL="postgresql://user:pass@host/db" python scripts/seed_demo_data.py',
        file=sys.stderr,
    )
    sys.exit(1)

from sqlalchemy import func, select  # noqa: E402

from app.core.database import AsyncSessionLocal, engine  # noqa: E402
from app.models.ai import AIDecision, AIPrediction  # noqa: E402
from app.models.audit import AuditLog  # noqa: E402
from app.models.emergency import EmergencyEvent  # noqa: E402
from app.models.event import Incident  # noqa: E402
from app.models.intersection import Intersection  # noqa: E402
from app.models.notification import Notification  # noqa: E402
from app.models.road import Road  # noqa: E402
from app.models.signal import Signal, SignalPhase  # noqa: E402
from app.models.traffic import TrafficRecord  # noqa: E402
from app.models.violation import Violation  # noqa: E402

# Deterministic RNG so re-runs (after manual cleanup) produce the same dataset.
rng = random.Random(20261014)

DEMO_TAG = "[DEMO]"

# ---------------------------------------------------------------------------
# 10 real Hyderabad intersections with approximate coordinates.
# (name, code, lat, lon, zone, base 5-min vehicle volume)
# ---------------------------------------------------------------------------
INTERSECTIONS = [
    ("Miyapur", "HYD-MIYAPUR", 17.4967, 78.3619, "West", 55),
    ("Kukatpally", "HYD-KUKATPALLY", 17.4849, 78.4138, "North-West", 65),
    ("Ameerpet", "HYD-AMEERPET", 17.4375, 78.4483, "Central", 70),
    ("Dilsukhnagar", "HYD-DILSUKHNAGAR", 17.3688, 78.5247, "East", 60),
    ("LB Nagar", "HYD-LBNAGAR", 17.3457, 78.5522, "East", 58),
    ("HITEC City", "HYD-HITECCITY", 17.4435, 78.3772, "West", 80),
    ("Gachibowli", "HYD-GACHIBOWLI", 17.4401, 78.3489, "West", 75),
    ("Secunderabad", "HYD-SECUNDERABAD", 17.4399, 78.4983, "North", 68),
    ("Begumpet", "HYD-BEGUMPET", 17.4448, 78.4653, "Central", 62),
    ("Malakpet", "HYD-MALAKPET", 17.3727, 78.4898, "South", 50),
]

RECORD_INTERVAL_MIN = 5
RECORDS_PER_DAY = 24 * 60 // RECORD_INTERVAL_MIN  # 288


def _gauss(x: float, mu: float, sigma: float) -> float:
    return math.exp(-((x - mu) ** 2) / (2 * sigma ** 2))


def time_multiplier(hour: float) -> float:
    """Share of peak traffic for a given hour of day (Hyderabad pattern).

    Morning peak ~08:30-10:30, evening peak ~17:30-20:00, near-empty overnight.
    """
    m = 0.10  # overnight baseline
    m += 0.90 * _gauss(hour, 9.25, 1.15)   # morning peak
    m += 0.55 * _gauss(hour, 13.50, 2.50)  # midday plateau
    m += 1.00 * _gauss(hour, 18.75, 1.35)  # evening peak
    m += 0.25 * _gauss(hour, 22.00, 1.20)  # late-evening taper
    return min(m, 1.05)


async def ensure_intersections(session) -> tuple[list[Intersection], int, int]:
    """Create the 10 demo intersections; skip any whose name already exists."""
    existing = {
        name for (name,) in (await session.execute(select(Intersection.name))).all()
    }
    created: list[Intersection] = []
    skipped = 0
    for name, code, lat, lon, zone, _base in INTERSECTIONS:
        if name in existing:
            skipped += 1
            continue
        created.append(
            Intersection(
                name=name,
                code=code,
                status="active",
                city="Hyderabad",
                zone=zone,
                lat=lat,
                lon=lon,
            )
        )
    if created:
        session.add_all(created)
        await session.flush()
    # Return ALL intersections (existing + new) for record generation.
    all_rows = (await session.execute(select(Intersection))).scalars().all()
    return list(all_rows), len(created), skipped


async def seed_traffic_records(session, intersections, start: datetime) -> int:
    """Generate 24h of 5-minute traffic records per intersection (source='demo')."""
    base_by_name = {name: base for name, _c, _la, _lo, _z, base in INTERSECTIONS}
    records: list[TrafficRecord] = []
    for ix in intersections:
        base = base_by_name.get(ix.name, 55)
        for slot in range(RECORDS_PER_DAY):
            ts = start + timedelta(minutes=RECORD_INTERVAL_MIN * slot)
            hour = ts.hour + ts.minute / 60.0
            load = time_multiplier(hour) * rng.uniform(0.85, 1.15)

            vehicle_count = max(0, int(base * load))
            congestion = int(min(100, max(2, load * 92 + rng.uniform(-6, 6))))
            # Speed falls as congestion rises: ~48 km/h free-flow, ~8 km/h gridlock.
            avg_speed = round(max(6.0, 52 - congestion * 0.44 + rng.uniform(-3, 3)), 1)

            records.append(
                TrafficRecord(
                    intersection_id=ix.id,
                    recorded_at=ts,
                    vehicle_count=vehicle_count,
                    avg_speed_kmh=avg_speed,
                    congestion_level=congestion,
                    source="demo",
                )
            )
    session.add_all(records)
    await session.flush()
    return len(records)


async def seed_violations(session, intersections, start: datetime) -> int:
    """Insert 12 sample violations (4x red_light, 4x wrong_way, 4x no_helmet)."""
    types = ["red_light"] * 4 + ["wrong_way"] * 4 + ["no_helmet"] * 4
    rng.shuffle(types)
    now = datetime.now(timezone.utc)
    rows: list[Violation] = []
    for i, vtype in enumerate(types):
        ix = rng.choice(intersections)
        detected = start + timedelta(
            seconds=rng.randint(0, int((now - start).total_seconds()))
        )
        rows.append(
            Violation(
                violation_type=vtype,
                detected_at=detected,
                intersection_id=ix.id,
                camera_id=f"DEMO-CAM-{rng.randint(1, 4):02d}",
                confidence=round(rng.uniform(0.72, 0.97), 2),
                status="recorded",
                details={
                    "demo": True,
                    "note": (
                        f"{DEMO_TAG} Sample {vtype} violation generated for "
                        "dashboard demonstration. Not a real detection."
                    ),
                    "track_id": f"DEMO-{i + 1:04d}",
                },
            )
        )
    session.add_all(rows)
    await session.flush()
    return len(rows)


async def seed_crash_incidents(session, intersections, start: datetime) -> int:
    """Insert 3 sample crash incidents, each description prefixed with [DEMO]."""
    now = datetime.now(timezone.utc)
    templates = [
        (
            "critical",
            "Sample multi-vehicle collision blocking two lanes; emergency "
            "services dispatched (simulated).",
        ),
        (
            "high",
            "Sample rear-end collision near the junction; one lane "
            "congested (simulated).",
        ),
        (
            "high",
            "Sample two-wheeler skid incident; traffic marshals alerted "
            "(simulated).",
        ),
    ]
    rows: list[Incident] = []
    for severity, text in templates:
        ix = rng.choice(intersections)
        rows.append(
            Incident(
                intersection_id=ix.id,
                severity=severity,
                status="reported",
                description=f"{DEMO_TAG} {text} Generated for dashboard "
                "demonstration — not a real incident.",
                lat=ix.lat,
                lon=ix.lon,
                created_at=start
                + timedelta(seconds=rng.randint(0, int((now - start).total_seconds()))),
            )
        )
    session.add_all(rows)
    await session.flush()
    return len(rows)


async def seed_signals(session, intersections) -> tuple[int, int]:
    """Create one demo Signal (+ 4 phases) per intersection.

    Statuses are varied (8 active, 1 maintenance, 1 fault) so the heuristic
    signal-health page shows a realistic spread. Codes are DEMO-prefixed.
    """
    statuses = ["active"] * 8 + ["maintenance", "fault"]
    rng.shuffle(statuses)
    observed = ["green", "yellow", "red", "green"]
    signals: list[Signal] = []
    phases: list[SignalPhase] = []
    for ix, status in zip(intersections, statuses):
        sig = Signal(
            intersection_id=ix.id,
            code=f"DEMO-{ix.code}",
            status=status,
            observed_state=rng.choice(observed) if status == "active" else "unknown",
            observed_confidence=round(rng.uniform(0.80, 0.99), 2)
            if status == "active"
            else None,
            observed_at=datetime.now(timezone.utc)
            if status == "active"
            else None,
        )
        signals.append(sig)
    session.add_all(signals)
    await session.flush()

    phase_defs = [
        ("North-South Green", 1, 45, "green"),
        ("North-South Yellow", 2, 5, "yellow"),
        ("East-West Green", 3, 40, "green"),
        ("East-West Yellow", 4, 5, "yellow"),
    ]
    for sig in signals:
        for i, (pname, order, duration, state) in enumerate(phase_defs):
            phases.append(
                SignalPhase(
                    signal_id=sig.id,
                    intersection_id=sig.intersection_id,
                    name=f"{DEMO_TAG} {pname}",
                    phase_order=order,
                    duration_seconds=duration + rng.randint(-5, 10),
                    state=state,
                    is_active=(i == 0),
                )
            )
    session.add_all(phases)
    await session.flush()
    return len(signals), len(phases)


async def seed_predictions(session, intersections, now: datetime) -> int:
    """Insert 24h of hourly LSTM-style flow forecasts per intersection.

    Payload carries uncertainty bands; model_version is demo-marked.
    """
    rows: list[AIPrediction] = []
    for ix in intersections:
        for h in range(24):
            ts = now + timedelta(hours=h + 1)
            hour = ts.hour + ts.minute / 60.0
            load = time_multiplier(hour) * rng.uniform(0.85, 1.15)
            base = 60
            predicted = max(0, int(base * load))
            half_band = max(3, int(predicted * rng.uniform(0.08, 0.18)))
            rows.append(
                AIPrediction(
                    intersection_id=ix.id,
                    prediction_type="flow",
                    predicted_for=ts,
                    payload={
                        "demo": True,
                        "note": (
                            f"{DEMO_TAG} Sample LSTM-style forecast for "
                            "dashboard demonstration. Not a real model output."
                        ),
                        "predicted_vehicle_count": predicted,
                        "lower_bound": max(0, predicted - half_band),
                        "upper_bound": predicted + half_band,
                        "predicted_congestion": int(min(100, max(2, load * 92))),
                        "horizon_hours": h + 1,
                    },
                    confidence=round(rng.uniform(0.70, 0.92), 2),
                    model_version="demo-lstm-v1",
                )
            )
    session.add_all(rows)
    await session.flush()
    return len(rows)


async def seed_decisions(
    session, intersections, predictions: list[AIPrediction]
) -> int:
    """Insert ~10 demo AI decisions: 5 signal_timing (Control page),
    3 route_advisory, 2 alert (Decisions page). All advisory/proposed."""
    now = datetime.now(timezone.utc)
    by_ix: dict[int, list[AIPrediction]] = {}
    for p in predictions:
        by_ix.setdefault(p.intersection_id, []).append(p)

    rows: list[AIDecision] = []

    # 5 signal-timing advisories (Control page)
    for ix in intersections[:5]:
        pred = (by_ix.get(ix.id) or [None])[0]
        rows.append(
            AIDecision(
                prediction_id=pred.id if pred else None,
                intersection_id=ix.id,
                decision_type="signal_timing",
                payload={
                    "demo": True,
                    "advisory": True,
                    "recommended_green_ns": rng.choice([40, 45, 50]),
                    "recommended_green_ew": rng.choice([30, 35, 40]),
                    "cycle_seconds": 120,
                    "note": "Webster-inspired queue-proportional recommendation.",
                },
                status="proposed",
                rationale=(
                    f"{DEMO_TAG} Advisory timing adjustment for {ix.name} based "
                    "on demo telemetry. Recommendations only — no hardware "
                    "control. Generated for dashboard demonstration."
                ),
                created_at=now - timedelta(hours=rng.randint(1, 20)),
            )
        )

    # 3 route advisories
    for ix in intersections[5:8]:
        rows.append(
            AIDecision(
                intersection_id=ix.id,
                decision_type="route_advisory",
                payload={
                    "demo": True,
                    "advisory": True,
                    "suggested_alternate": f"Via {rng.choice(intersections).name}",
                    "expected_delay_saving_min": rng.randint(3, 12),
                },
                status="proposed",
                rationale=(
                    f"{DEMO_TAG} Congestion-aware alternate route suggestion "
                    f"near {ix.name}. Generated for dashboard demonstration."
                ),
                created_at=now - timedelta(hours=rng.randint(1, 20)),
            )
        )

    # 2 alerts
    for ix in intersections[8:10]:
        rows.append(
            AIDecision(
                intersection_id=ix.id,
                decision_type="alert",
                payload={
                    "demo": True,
                    "alert": "congestion_buildup",
                    "severity": "warning",
                },
                status="proposed",
                rationale=(
                    f"{DEMO_TAG} Automated congestion-buildup alert for "
                    f"{ix.name}. Generated for dashboard demonstration."
                ),
                created_at=now - timedelta(hours=rng.randint(1, 20)),
            )
        )

    session.add_all(rows)
    await session.flush()
    return len(rows)


async def seed_notifications(
    session, intersections, incidents: list[Incident]
) -> int:
    """Insert ~10 demo broadcast notifications (all [DEMO] prefixed)."""
    now = datetime.now(timezone.utc)
    specs = [
        ("warning", "intersection",
         f"{DEMO_TAG} Congestion building at {intersections[1].name}",
         f"{DEMO_TAG} Demo telemetry shows congestion rising above 80% at "
         f"{intersections[1].name} during the evening peak window. Sample alert."),
        ("warning", "intersection",
         f"{DEMO_TAG} Congestion building at {intersections[5].name}",
         f"{DEMO_TAG} Demo telemetry shows congestion rising above 85% at "
         f"{intersections[5].name}. Sample alert."),
        ("critical", "incident",
         f"{DEMO_TAG} Crash reported near {intersections[0].name}",
         f"{DEMO_TAG} Sample crash incident generated for demonstration. "
         "Not a real incident."),
        ("error", "incident",
         f"{DEMO_TAG} Violation spike detected",
         f"{DEMO_TAG} Sample red-light violation cluster generated for "
         "demonstration. Not real detections."),
        ("warning", "signal",
         f"{DEMO_TAG} Signal controller in maintenance",
         f"{DEMO_TAG} One demo signal controller is flagged for maintenance; "
         "health score reflects this. Sample notice."),
        ("info", "system",
         f"{DEMO_TAG} Demo dataset loaded",
         f"{DEMO_TAG} Sample Hyderabad telemetry dataset was loaded for "
         "dashboard demonstration. All figures are synthetic."),
        ("info", "system",
         f"{DEMO_TAG} TomTom live traffic layer enabled",
         f"{DEMO_TAG} Sample notice: the map's live traffic overlay is "
         "configured. Demonstration notice."),
        ("warning", "intersection",
         f"{DEMO_TAG} Event demand uplift forecast ready",
         f"{DEMO_TAG} Sample notice: a demo event-demand forecast was "
         "generated for the stadium event scenario."),
        ("info", "assistant",
         f"{DEMO_TAG} AI assistant online",
         f"{DEMO_TAG} Sample notice: the Gemini-powered traffic assistant "
         "is available. Demonstration notice."),
        ("info", "emergency",
         f"{DEMO_TAG} Emergency drill completed",
         f"{DEMO_TAG} Sample emergency-response drill record. Not a real "
         "emergency."),
    ]
    rows: list[Notification] = []
    for i, (severity, entity_type, title, message) in enumerate(specs):
        entity_id = None
        if entity_type == "intersection":
            entity_id = rng.choice(intersections).id
        elif entity_type == "incident" and incidents:
            entity_id = rng.choice(incidents).id
        rows.append(
            Notification(
                user_id=None,  # broadcast
                title=title,
                message=message,
                severity=severity,
                is_read=(i % 3 == 0),
                entity_type=entity_type,
                entity_id=entity_id,
                created_at=now - timedelta(hours=rng.randint(0, 20)),
            )
        )
    session.add_all(rows)
    await session.flush()
    return len(rows)


async def seed_emergency_events(
    session, incidents: list[Incident]
) -> int:
    """Insert demo emergency events linked to the [DEMO] crash incidents.

    EmergencyEvent has no free-text field, so demo labeling is carried by the
    linked [DEMO] incidents.
    """
    now = datetime.now(timezone.utc)
    vehicle_types = ["ambulance", "fire", "police", "ambulance"]
    statuses = ["resolved", "dispatched", "active", "on_scene"]
    rows: list[EmergencyEvent] = []
    for incident, vtype, status in zip(incidents, vehicle_types, statuses):
        detected = now - timedelta(hours=rng.randint(1, 18))
        rows.append(
            EmergencyEvent(
                incident_id=incident.id,
                vehicle_type=vtype,
                priority=rng.randint(1, 2),
                status=status,
                detected_at=detected,
                cleared_at=detected + timedelta(minutes=rng.randint(20, 60))
                if status == "resolved"
                else None,
            )
        )
    session.add_all(rows)
    await session.flush()
    return len(rows)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


async def seed_roads(session, by_name: dict[str, Intersection]) -> int:
    """Insert 4 demo corridors between Hyderabad intersections.

    The Routing page builds its graph from the roads table.
    """
    pairs = [
        ("Miyapur", "Kukatpally", "arterial", 60),
        ("HITEC City", "Gachibowli", "arterial", 60),
        ("Ameerpet", "Begumpet", "collector", 50),
        ("Dilsukhnagar", "LB Nagar", "arterial", 60),
    ]
    rows: list[Road] = []
    for a_name, b_name, road_type, speed in pairs:
        a, b = by_name[a_name], by_name[b_name]
        length = round(_haversine_km(a.lat, a.lon, b.lat, b.lon), 2)
        geometry = (
            '{"type":"LineString","coordinates":[[%s,%s],[%s,%s]]}'
            % (a.lon, a.lat, b.lon, b.lat)
        )
        rows.append(
            Road(
                name=f"{DEMO_TAG} {a_name} – {b_name} Corridor",
                road_type=road_type,
                speed_limit_kmh=speed,
                geometry=geometry,
                from_intersection_id=a.id,
                to_intersection_id=b.id,
                length_km=length,
                capacity_veh_per_hr=rng.choice([1800, 2400, 3200]),
                is_bidirectional=True,
            )
        )
    session.add_all(rows)
    await session.flush()
    return len(rows)


async def seed_audit_logs(
    session,
    intersections: list[Intersection],
    incidents: list[Incident],
    decisions: list[AIDecision],
) -> int:
    """Insert demo audit trail entries (details carry demo=True)."""
    now = datetime.now(timezone.utc)
    specs = [
        ("demo.dataset.loaded", "system", None,
         {"demo": True, "note": f"{DEMO_TAG} Demo dataset load recorded."}),
        ("auth.login", "user", None,
         {"demo": True, "note": f"{DEMO_TAG} Sample operator sign-in."}),
        ("signal.updated", "signal", None,
         {"demo": True, "note": f"{DEMO_TAG} Sample signal timing review."}),
        ("incident.acknowledged", "incident",
         incidents[0].id if incidents else None,
         {"demo": True, "note": f"{DEMO_TAG} Sample incident acknowledgement."}),
        ("assistant.query", "assistant", None,
         {"demo": True,
          "note": f"{DEMO_TAG} Sample AI assistant query about congestion."}),
        ("decision.proposed", "ai_decision",
         decisions[0].id if decisions else None,
         {"demo": True, "note": f"{DEMO_TAG} Sample advisory decision logged."}),
        ("violation.recorded", "violation", None,
         {"demo": True, "note": f"{DEMO_TAG} Sample violation ingest."}),
        ("event_demand.forecast_generated", "event_demand", None,
         {"demo": True,
          "note": f"{DEMO_TAG} Sample stadium event forecast run."}),
    ]
    rows: list[AuditLog] = []
    for action, entity_type, entity_id, details in specs:
        rows.append(
            AuditLog(
                actor_user_id=None,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                details=details,
                ip_address="127.0.0.1",
                created_at=now - timedelta(hours=rng.randint(0, 20)),
            )
        )
    session.add_all(rows)
    await session.flush()
    return len(rows)


async def main() -> None:
    async with AsyncSessionLocal() as session:
        # --- Intersections (idempotent by name) ---------------------------
        intersections, created_n, skipped_n = await ensure_intersections(session)
        by_name = {ix.name: ix for ix in intersections}

        # --- Demo telemetry (skip if already seeded) -----------------------
        demo_records = (
            await session.execute(
                select(func.count())
                .select_from(TrafficRecord)
                .where(TrafficRecord.source == "demo")
            )
        ).scalar_one()
        demo_violations = (
            await session.execute(select(func.count()).select_from(Violation))
        ).scalar_one()

        records_n = 0
        violations_n = 0
        incidents_n = 0

        if demo_records == 0:
            end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
            start = end - timedelta(hours=24)
            records_n = await seed_traffic_records(session, intersections, start)
            violations_n = await seed_violations(session, intersections, start)
            incidents_n = await seed_crash_incidents(session, intersections, start)
            await session.commit()
        else:
            print(
                f"Demo telemetry already present ({demo_records} records with "
                "source='demo'); skipping record/violation/incident generation."
            )
            await session.commit()  # persist any new intersections

        # Demo incidents (for notifications / emergency linkage)
        demo_incidents = (
            await session.execute(
                select(Incident).where(Incident.description.like(f"{DEMO_TAG}%"))
            )
        ).scalars().all()

        # --- Signals + phases (idempotent on DEMO- code prefix) -----------
        demo_signals = (
            await session.execute(
                select(func.count())
                .select_from(Signal)
                .where(Signal.code.like("DEMO-%"))
            )
        ).scalar_one()
        signals_n = phases_n = 0
        if demo_signals == 0:
            signals_n, phases_n = await seed_signals(session, intersections)
            await session.commit()
        else:
            print(
                f"Demo signals already present ({demo_signals}); skipping "
                "signal/phase generation."
            )

        # --- Predictions (idempotent on demo model version) ---------------
        demo_predictions = (
            await session.execute(
                select(func.count())
                .select_from(AIPrediction)
                .where(AIPrediction.model_version == "demo-lstm-v1")
            )
        ).scalar_one()
        predictions_n = 0
        predictions: list[AIPrediction] = []
        if demo_predictions == 0:
            predictions_n = await seed_predictions(
                session, intersections, datetime.now(timezone.utc)
            )
            await session.commit()
            predictions = (
                await session.execute(
                    select(AIPrediction).where(
                        AIPrediction.model_version == "demo-lstm-v1"
                    )
                )
            ).scalars().all()
        else:
            print(
                f"Demo predictions already present ({demo_predictions}); "
                "skipping forecast generation."
            )
            predictions = (
                await session.execute(
                    select(AIPrediction).where(
                        AIPrediction.model_version == "demo-lstm-v1"
                    )
                )
            ).scalars().all()

        # --- Decisions (idempotent on [DEMO] rationale) --------------------
        demo_decisions = (
            await session.execute(
                select(func.count())
                .select_from(AIDecision)
                .where(AIDecision.rationale.like(f"{DEMO_TAG}%"))
            )
        ).scalar_one()
        decisions_n = 0
        decisions: list[AIDecision] = []
        if demo_decisions == 0:
            decisions_n = await seed_decisions(session, intersections, predictions)
            await session.commit()
            decisions = (
                await session.execute(
                    select(AIDecision).where(
                        AIDecision.rationale.like(f"{DEMO_TAG}%")
                    )
                )
            ).scalars().all()
        else:
            print(
                f"Demo decisions already present ({demo_decisions}); skipping "
                "decision generation."
            )
            decisions = (
                await session.execute(
                    select(AIDecision).where(
                        AIDecision.rationale.like(f"{DEMO_TAG}%")
                    )
                )
            ).scalars().all()

        # --- Notifications (idempotent on [DEMO] title) --------------------
        demo_notifications = (
            await session.execute(
                select(func.count())
                .select_from(Notification)
                .where(Notification.title.like(f"{DEMO_TAG}%"))
            )
        ).scalar_one()
        notifications_n = 0
        if demo_notifications == 0:
            notifications_n = await seed_notifications(
                session, intersections, list(demo_incidents)
            )
            await session.commit()
        else:
            print(
                f"Demo notifications already present ({demo_notifications}); "
                "skipping notification generation."
            )

        # --- Emergency events (linked to [DEMO] incidents) -----------------
        demo_emergencies = (
            await session.execute(select(func.count()).select_from(EmergencyEvent))
        ).scalar_one()
        emergencies_n = 0
        if demo_emergencies == 0 and demo_incidents:
            emergencies_n = await seed_emergency_events(
                session, list(demo_incidents)
            )
            await session.commit()
        else:
            print(
                "Emergency events already present "
                f"({demo_emergencies}) or no demo incidents; skipping."
            )

        # --- Roads / corridors (idempotent on [DEMO] name) -----------------
        demo_roads = (
            await session.execute(
                select(func.count())
                .select_from(Road)
                .where(Road.name.like(f"{DEMO_TAG}%"))
            )
        ).scalar_one()
        roads_n = 0
        if demo_roads == 0:
            roads_n = await seed_roads(session, by_name)
            await session.commit()
        else:
            print(
                f"Demo roads already present ({demo_roads}); skipping "
                "corridor generation."
            )

        # --- Audit logs (idempotent on demo.seed action) -------------------
        demo_audits = (
            await session.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "demo.dataset.loaded")
            )
        ).scalar_one()
        audits_n = 0
        if demo_audits == 0:
            audits_n = await seed_audit_logs(
                session, intersections, list(demo_incidents), decisions
            )
            await session.commit()
        else:
            print("Demo audit entries already present; skipping audit seeding.")

        print("---- Seed summary ----")
        print(f"Intersections: {created_n} created, {skipped_n} already existed")
        print(f"Traffic records (source='demo'): {records_n} inserted")
        print(f"Violations (demo-labeled): {violations_n} inserted")
        print(f"Crash incidents ([DEMO] labeled): {incidents_n} inserted")
        print(f"Signals: {signals_n} inserted, signal phases: {phases_n} inserted")
        print(f"AI predictions (demo-lstm-v1): {predictions_n} inserted")
        print(f"AI decisions ([DEMO] rationale): {decisions_n} inserted")
        print(f"Notifications ([DEMO] broadcast): {notifications_n} inserted")
        print(f"Emergency events (linked to [DEMO] incidents): {emergencies_n} inserted")
        print(f"Roads/corridors ([DEMO]): {roads_n} inserted")
        print(f"Audit log entries (demo): {audits_n} inserted")
        print("All generated rows are explicitly marked as demo/sample data.")

    await engine.dispose()


if __name__ == "__main__":
    try:
        import asyncio

        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001 - surface any failure plainly
        print(f"ERROR: seeding failed: {exc}", file=sys.stderr)
        sys.exit(1)
