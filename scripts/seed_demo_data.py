#!/usr/bin/env python3
"""Seed clearly-labeled DEMO traffic data for AI TrafficOS dashboards.

The production database has no live sensors connected, so every data page
renders empty. This script inserts a realistic 24-hour sample dataset for
Hyderabad intersections so dashboards, maps, predictions, and incident pages
come alive for demo / portfolio purposes.

HONESTY CONTRACT: every generated row is explicitly labeled as demo/sample:
  - TrafficRecord.source = "demo"
  - Violation.details contains {"demo": True, ...} with a [DEMO] note
  - Incident.description is prefixed with "[DEMO]"
No generated row is ever presented as a real sensor reading or detection.

Usage:
    DATABASE_URL="postgresql://..." python scripts/seed_demo_data.py

Run from the repository root. Requires DATABASE_URL in the environment.
Idempotent: intersections are matched by name; demo traffic records,
violations, and incidents are skipped if demo data already exists.
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
from app.models.event import Incident  # noqa: E402
from app.models.intersection import Intersection  # noqa: E402
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


async def main() -> None:
    async with AsyncSessionLocal() as session:
        # --- Intersections (idempotent by name) ---------------------------
        intersections, created_n, skipped_n = await ensure_intersections(session)

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

        print("---- Seed summary ----")
        print(f"Intersections: {created_n} created, {skipped_n} already existed")
        print(f"Traffic records (source='demo'): {records_n} inserted")
        print(f"Violations (demo-labeled): {violations_n} inserted")
        print(f"Crash incidents ([DEMO] labeled): {incidents_n} inserted")
        print("All generated rows are explicitly marked as demo/sample data.")

    await engine.dispose()


if __name__ == "__main__":
    try:
        import asyncio

        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001 - surface any failure plainly
        print(f"ERROR: seeding failed: {exc}", file=sys.stderr)
        sys.exit(1)
