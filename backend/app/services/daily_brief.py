"""Daily traffic operations brief generation service.

Aggregates observed incidents and violations from PostgreSQL, retrieves forward
hotspot predictions from ai_predictions, computes day-over-day trends with honest
history tracking, and provides optional rephrasing via the grounded GeminiProvider.
"""

from datetime import date, datetime, time, timedelta, timezone
import logging
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.assistant.providers import GeminiProvider
from app.models.ai import AIPrediction
from app.models.event import Incident
from app.models.violation import Violation

logger = logging.getLogger(__name__)


def format_deterministic_summary(
    date_str: str,
    incidents_data: dict[str, Any],
    violations_data: dict[str, Any],
    hotspots_data: dict[str, Any],
    trends_data: dict[str, Any],
) -> str:
    """Format structured brief sections into a deterministic Markdown narrative."""
    lines: list[str] = [
        f"# Daily Traffic Operations Brief — {date_str}",
        "",
        "## Observed Incidents (Yesterday)",
    ]

    if incidents_data["has_data"] and incidents_data["count"] is not None:
        lines.append(f"- **Total Incidents:** {incidents_data['count']}")
        if incidents_data["by_severity"]:
            sev_str = ", ".join(f"{k}: {v}" for k, v in sorted(incidents_data["by_severity"].items()))
            lines.append(f"- **Severity Breakdown:** {sev_str}")
    else:
        lines.append(f"- *{incidents_data['note'] or 'No incident data recorded for yesterday.'}*")

    lines.append("")
    lines.append("## Observed Violations (Yesterday)")
    if violations_data["has_data"] and violations_data["count"] is not None:
        lines.append(f"- **Total Violations:** {violations_data['count']}")
        if violations_data["by_type"]:
            type_str = ", ".join(f"{k}: {v}" for k, v in sorted(violations_data["by_type"].items()))
            lines.append(f"- **Violation Types:** {type_str}")
    else:
        lines.append(f"- *{violations_data['note'] or 'No violation records found for yesterday.'}*")

    lines.append("")
    lines.append("## Forecasted Hotspots (Today)")
    if hotspots_data["has_data"] and hotspots_data["items"]:
        lines.append("Model forecasts indicate potential congestion elevation at:")
        for item in hotspots_data["items"]:
            cong = f"{item['predicted_congestion']:.1f}%" if item.get("predicted_congestion") is not None else "N/A"
            lines.append(
                f"- **{item['intersection_name']}** (ID: {item['intersection_id']}): "
                f"predicted congestion {cong} (confidence: {item.get('confidence', 0.0):.2f})"
            )
    else:
        lines.append(f"- *{hotspots_data['note'] or 'No forward hotspot predictions available for today.'}*")

    lines.append("")
    lines.append("## Operational Trends & Deltas")
    if trends_data["has_sufficient_history"]:
        inc_delta = trends_data["incident_delta"]
        viol_delta = trends_data["violation_delta"]
        inc_str = f"{inc_delta:+d}" if inc_delta is not None else "0"
        viol_str = f"{viol_delta:+d}" if viol_delta is not None else "0"
        lines.append(
            f"- **Day-over-Day Change:** {inc_str} incidents, {viol_str} violations compared to prior day."
        )
    else:
        lines.append(f"- *{trends_data['note'] or 'Insufficient history (<2 days of data) to compute day-over-day trends.'}*")

    return "\n".join(lines)


async def generate_daily_brief(
    db: AsyncSession,
    target_date: Optional[date] = None,
    rephrase: bool = False,
    now_override: Optional[datetime] = None,
) -> dict[str, Any]:
    """Generate daily morning traffic operations brief.

    Args:
        db: Active asynchronous SQLAlchemy session.
        target_date: Target date of interest for yesterday's observed data (defaults to yesterday).
        rephrase: Whether to run summary through GeminiProvider (falls back silently without API key).
        now_override: Optional datetime override for deterministic testing.

    Returns:
        Structured dictionary matching DailyBriefResponse.
    """
    now = now_override or datetime.now(timezone.utc)
    today = now.date()

    if target_date is not None:
        yesterday = target_date
        today = yesterday + timedelta(days=1)
    else:
        yesterday = today - timedelta(days=1)

    start_of_yesterday = datetime.combine(yesterday, time.min, tzinfo=timezone.utc)
    end_of_yesterday = datetime.combine(yesterday, time.max, tzinfo=timezone.utc)

    day_before = yesterday - timedelta(days=1)
    start_of_day_before = datetime.combine(day_before, time.min, tzinfo=timezone.utc)
    end_of_day_before = datetime.combine(day_before, time.max, tzinfo=timezone.utc)

    start_of_today = datetime.combine(today, time.min, tzinfo=timezone.utc)
    end_of_today = datetime.combine(today, time.max, tzinfo=timezone.utc)

    # 1. Real Query: Yesterday's Incidents
    inc_stmt = (
        select(Incident.severity, func.count(Incident.id))
        .where(
            Incident.created_at >= start_of_yesterday,
            Incident.created_at <= end_of_yesterday,
        )
        .group_by(Incident.severity)
    )
    inc_res = await db.execute(inc_stmt)
    inc_rows = inc_res.all()
    inc_by_sev = {row[0]: int(row[1]) for row in inc_rows if row[0] is not None}
    inc_total = sum(inc_by_sev.values())

    if inc_total > 0:
        incidents_data = {
            "provenance": "observed",
            "has_data": True,
            "count": inc_total,
            "total": inc_total,
            "by_severity": inc_by_sev,
            "by_type": inc_by_sev,
            "note": None,
        }
    else:
        incidents_data = {
            "provenance": "observed",
            "has_data": False,
            "count": None,
            "total": None,
            "by_severity": {},
            "by_type": {},
            "note": "No incident data recorded for yesterday.",
        }

    # 2. Real Query: Yesterday's Violations
    viol_stmt = (
        select(Violation.violation_type, func.count(Violation.id))
        .where(
            Violation.detected_at >= start_of_yesterday,
            Violation.detected_at <= end_of_yesterday,
        )
        .group_by(Violation.violation_type)
    )
    viol_res = await db.execute(viol_stmt)
    viol_rows = viol_res.all()
    viol_by_type = {row[0]: int(row[1]) for row in viol_rows if row[0] is not None}
    viol_total = sum(viol_by_type.values())

    if viol_total > 0:
        violations_data = {
            "provenance": "observed",
            "has_data": True,
            "count": viol_total,
            "total": viol_total,
            "by_type": viol_by_type,
            "note": None,
        }
    else:
        violations_data = {
            "provenance": "observed",
            "has_data": False,
            "count": None,
            "total": None,
            "by_type": {},
            "note": "No violation records found for yesterday.",
        }

    # 3. Real Query: Today's Predicted Hotspots (AIPrediction)
    pred_stmt = (
        select(AIPrediction)
        .options(selectinload(AIPrediction.intersection))
        .where(
            AIPrediction.predicted_for >= start_of_today,
            AIPrediction.predicted_for <= end_of_today,
        )
        .order_by(AIPrediction.confidence.desc())
    )
    pred_res = await db.execute(pred_stmt)
    predictions = list(pred_res.scalars().all())

    hotspot_items: list[dict[str, Any]] = []
    seen_junctions: set[int] = set()

    for p in predictions:
        if p.intersection_id in seen_junctions:
            continue
        payload = p.payload or {}
        cong_val = payload.get("congestion") if payload.get("congestion") is not None else payload.get("value")
        flow_val = payload.get("value") if p.prediction_type == "flow" else None

        j_name = p.intersection.name if p.intersection else f"Intersection {p.intersection_id}"
        j_code = p.intersection.code if p.intersection else None

        hotspot_items.append({
            "intersection_id": p.intersection_id,
            "intersection_name": j_name,
            "intersection_code": j_code,
            "predicted_congestion": float(cong_val) if cong_val is not None else None,
            "predicted_flow": float(flow_val) if flow_val is not None else None,
            "confidence": p.confidence,
            "predicted_for": p.predicted_for,
        })
        if p.intersection_id is not None:
            seen_junctions.add(p.intersection_id)
        if len(hotspot_items) >= 5:
            break

    if hotspot_items:
        hotspots_data = {
            "provenance": "predicted",
            "has_data": True,
            "items": hotspot_items,
            "note": None,
        }
    else:
        hotspots_data = {
            "provenance": "predicted",
            "has_data": False,
            "items": [],
            "note": "No forward hotspot predictions available for today. Model inference has not been triggered.",
        }

    # 4. Real Query: Day-over-Day Trends & History Validation
    # Day before yesterday
    prev_inc_stmt = select(func.count(Incident.id)).where(
        Incident.created_at >= start_of_day_before,
        Incident.created_at <= end_of_day_before,
    )
    prev_inc_res = await db.execute(prev_inc_stmt)
    prev_inc_count = prev_inc_res.scalar() or 0

    prev_viol_stmt = select(func.count(Violation.id)).where(
        Violation.detected_at >= start_of_day_before,
        Violation.detected_at <= end_of_day_before,
    )
    prev_viol_res = await db.execute(prev_viol_stmt)
    prev_viol_count = prev_viol_res.scalar() or 0

    # Check earliest data points across tables to honestly determine if >= 2 days of history exist
    earliest_inc_stmt = select(func.min(Incident.created_at))
    earliest_inc_res = await db.execute(earliest_inc_stmt)
    earliest_inc = earliest_inc_res.scalar()

    earliest_viol_stmt = select(func.min(Violation.detected_at))
    earliest_viol_res = await db.execute(earliest_viol_stmt)
    earliest_viol = earliest_viol_res.scalar()

    dates = [d for d in [earliest_inc, earliest_viol] if d is not None]

    # If no data at all in the database, or earliest record starts on or after start_of_yesterday
    # then we strictly have < 2 days of recorded history
    has_sufficient_history = False
    if dates:
        earliest_dt = min(dates)
        if earliest_dt < start_of_yesterday:
            has_sufficient_history = True

    if has_sufficient_history:
        current_inc = inc_total if inc_total > 0 else 0
        current_viol = viol_total if viol_total > 0 else 0
        inc_delta = current_inc - prev_inc_count
        viol_delta = current_viol - prev_viol_count

        direction = "stable"
        if inc_delta > 0 or viol_delta > 0:
            direction = "increased"
        elif inc_delta < 0 or viol_delta < 0:
            direction = "decreased"

        trends_data = {
            "provenance": "observed",
            "has_sufficient_history": True,
            "incident_delta": inc_delta,
            "violation_delta": viol_delta,
            "direction": direction,
            "note": f"Day-over-day changes: {inc_delta:+d} incidents, {viol_delta:+d} violations compared to prior day.",
        }
    else:
        trends_data = {
            "provenance": "observed",
            "has_sufficient_history": False,
            "incident_delta": None,
            "violation_delta": None,
            "direction": None,
            "note": "Insufficient history (<2 days of data) to compute day-over-day trends.",
        }

    # 5. Deterministic Summary Text
    date_str = yesterday.isoformat()
    deterministic_text = format_deterministic_summary(
        date_str=date_str,
        incidents_data=incidents_data,
        violations_data=violations_data,
        hotspots_data=hotspots_data,
        trends_data=trends_data,
    )

    final_text = deterministic_text
    rephrase_applied = False

    if rephrase:
        provider = GeminiProvider()
        rephrased_text = await provider.rephrase_brief(deterministic_text)
        if rephrased_text and rephrased_text != deterministic_text:
            final_text = rephrased_text
            rephrase_applied = True

    return {
        "generated_at": now,
        "date": date_str,
        "summary_text": final_text,
        "rephrased": rephrase_applied,
        "incidents": incidents_data,
        "violations": violations_data,
        "hotspots": hotspots_data,
        "trends": trends_data,
    }
