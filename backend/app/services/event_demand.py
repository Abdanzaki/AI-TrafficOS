"""Event demand forecasting service.

Implements a transparent parametric gravity heuristic to project traffic demand
uplift across nearby junctions for planned events (stadium games, concerts, festivals).
Exposes all assumptions, parameter ranges, and formulas honestly without ML claims.
"""

from datetime import datetime, timedelta, timezone
import logging
import math
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intersection import Intersection
from app.models.traffic import TrafficRecord

logger = logging.getLogger(__name__)

# Documented assumption parameter definitions
ASSUMPTION_DEFINITIONS = [
    {
        "parameter": "mode_share",
        "description": "Proportion of event attendees traveling via private motor vehicle",
        "range_or_value": "Low: 35%, Base: 50%, High: 65%",
        "low": 0.35,
        "base": 0.50,
        "high": 0.65,
        "formula": "mode_share: fraction of total attendance utilizing private personal vehicles",
    },
    {
        "parameter": "vehicle_occupancy",
        "description": "Average vehicle occupancy rate (persons per vehicle)",
        "range_or_value": "Low: 1.8 pers/veh, Base: 1.5 pers/veh, High: 1.2 pers/veh",
        "low": 1.8,
        "base": 1.5,
        "high": 1.2,
        "formula": "total_event_vehicles = (attendance * mode_share) / vehicle_occupancy",
    },
    {
        "parameter": "peak_arrival_share",
        "description": "Fraction of event vehicular trips arriving in peak 60-minute window prior to start",
        "range_or_value": "Low: 60%, Base: 75%, High: 90%",
        "low": 0.60,
        "base": 0.75,
        "high": 0.90,
        "formula": "peak_vehicles = total_event_vehicles * peak_arrival_share",
    },
    {
        "parameter": "spatial_gravity_distribution",
        "description": "Inverse-square distance decay formula regularized by 0.5 km minimum distance",
        "range_or_value": "w_i = 1.0 / (d_i + 0.5)^2; W_i = w_i / sum(w)",
        "low": None,
        "base": None,
        "high": None,
        "formula": "w_i = 1.0 / ((distance_km + 0.5) ** 2); normalized_weight_i = w_i / sum(w)",
    },
]


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate great-circle distance between two geographic coordinates in kilometers."""
    r = 6371.0  # Earth radius in kilometers
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


def calculate_peak_vehicles(attendance: int) -> dict[str, int]:
    """Calculate network-wide peak arrival vehicular volumes under Low, Base, and High scenarios.

    Formula:
        V = attendance * (mode_share / occupancy) * peak_arrival_share
    """
    # Low scenario: 35% mode share, 1.8 occupancy, 60% peak arrival
    v_low = round(attendance * (0.35 / 1.8) * 0.60)
    # Base scenario: 50% mode share, 1.5 occupancy, 75% peak arrival
    v_base = round(attendance * (0.50 / 1.5) * 0.75)
    # High scenario: 65% mode share, 1.2 occupancy, 90% peak arrival
    v_high = round(attendance * (0.65 / 1.2) * 0.90)

    return {
        "low": max(1, v_low),
        "base": max(1, v_base),
        "high": max(1, v_high),
    }


def calculate_spatial_weights(distances_km: list[float]) -> list[float]:
    """Compute normalized gravity model shares across junctions based on distance."""
    if not distances_km:
        return []

    raw_weights = [1.0 / ((d + 0.5) ** 2) for d in distances_km]
    total_w = sum(raw_weights)
    if total_w <= 0.0:
        return [1.0 / len(distances_km)] * len(distances_km)

    return [w / total_w for w in raw_weights]


def compute_scenario_uplift(
    peak_vehicles: int,
    spatial_weight: float,
    baseline_flow: Optional[float],
) -> dict[str, Any]:
    """Compute junction uplift and projected total flow for a single scenario."""
    uplift = round(peak_vehicles * spatial_weight)
    if baseline_flow is not None:
        projected = round(baseline_flow + uplift, 1)
        pct = round((uplift / baseline_flow) * 100.0, 1) if baseline_flow > 0 else None
    else:
        projected = None
        pct = None

    return {
        "uplift_vehicles": uplift,
        "projected_total_flow": projected,
        "uplift_percentage": pct,
    }


async def forecast_event_demand(
    db: AsyncSession,
    name: str,
    starts_at: datetime,
    expected_attendance: int,
    junction_id: Optional[int] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    k_nearest: int = 3,
) -> dict[str, Any]:
    """Execute transparent parametric heuristic demand forecasting for an event.

    Args:
        db: Active asynchronous SQLAlchemy session.
        name: Name of the event.
        starts_at: Scheduled start time of the event.
        expected_attendance: Expected attendee volume (> 0).
        junction_id: Host junction identifier (if known).
        lat: Latitude of event venue (if known).
        lng: Longitude of event venue (if known).
        k_nearest: Count of neighboring junctions to evaluate.

    Returns:
        Structured dictionary conforming to EventDemandResponse.
    """
    # 1. Resolve host location coordinates
    venue_lat = lat
    venue_lng = lng
    host_junction: Optional[Intersection] = None

    if junction_id is not None:
        host_junction = await db.get(Intersection, junction_id)
        if not host_junction:
            raise ValueError(f"Junction with id {junction_id} not found in database.")
        if venue_lat is None:
            venue_lat = host_junction.lat
        if venue_lng is None:
            venue_lng = host_junction.lon

    if venue_lat is None or venue_lng is None:
        # Default city center fallback coordinates if junctions lack spatial data
        venue_lat = 37.7749
        venue_lng = -122.4194

    # 2. Query all active physical intersections
    stmt = select(Intersection).where(Intersection.status == "active")
    res = await db.execute(stmt)
    all_intersections = list(res.scalars().all())

    # Fallback to all intersections if none explicitly active
    if not all_intersections:
        stmt = select(Intersection)
        res = await db.execute(stmt)
        all_intersections = list(res.scalars().all())

    # Rank junctions by distance
    candidate_junctions: list[tuple[Intersection, float]] = []
    for inter in all_intersections:
        if junction_id is not None and inter.id == junction_id:
            # Host junction has distance 0.0
            candidate_junctions.append((inter, 0.0))
            continue

        if inter.lat is not None and inter.lon is not None:
            dist = haversine_distance_km(venue_lat, venue_lng, inter.lat, inter.lon)
        else:
            # Nominal distance for un-geocoded intersections based on ID distance
            diff = abs(inter.id - (junction_id or 1))
            dist = 1.0 + (diff * 0.5)

        candidate_junctions.append((inter, dist))

    # Sort strictly by distance ascending
    candidate_junctions.sort(key=lambda x: x[1])

    # Select top k, guaranteeing host_junction is included first if explicitly supplied
    if host_junction is not None:
        remaining = [c for c in candidate_junctions if c[0].id != host_junction.id]
        selected = [(host_junction, 0.0)] + remaining[: max(0, k_nearest - 1)]
    else:
        selected = candidate_junctions[:k_nearest]

    if not selected and host_junction:
        selected = [(host_junction, 0.0)]

    distances = [dist for _, dist in selected]
    spatial_shares = calculate_spatial_weights(distances)

    # 3. Calculate peak arrival vehicles across scenarios
    peak_vehicles = calculate_peak_vehicles(expected_attendance)

    # 4. Query real baseline telemetry flow for selected junctions
    now = datetime.now(timezone.utc)
    lookback_cutoff = now - timedelta(days=2)

    junction_results: list[dict[str, Any]] = []

    for idx, (inter, dist) in enumerate(selected):
        weight = spatial_shares[idx]

        # Query recent traffic flow from TrafficRecord
        flow_stmt = select(
            func.avg(TrafficRecord.vehicle_count),
            func.count(TrafficRecord.id),
        ).where(
            TrafficRecord.intersection_id == inter.id,
            TrafficRecord.recorded_at >= lookback_cutoff,
        )
        flow_res = await db.execute(flow_stmt)
        avg_val, rec_count = flow_res.first() or (None, 0)

        # Fallback to any lifetime records if recent 48h has none
        if (rec_count is None or rec_count == 0):
            lifetime_stmt = select(
                func.avg(TrafficRecord.vehicle_count),
                func.count(TrafficRecord.id),
            ).where(
                TrafficRecord.intersection_id == inter.id,
            )
            lifetime_res = await db.execute(lifetime_stmt)
            avg_val, rec_count = lifetime_res.first() or (None, 0)

        if rec_count and rec_count > 0 and avg_val is not None:
            baseline_flow = round(float(avg_val), 1)
            baseline_status = "observed"
            baseline_note = None
        else:
            baseline_flow = None
            baseline_status = "no_baseline_data"
            baseline_note = (
                f"No historical telemetry observations recorded for junction {inter.id} ({inter.name}). "
                "Baseline flow cannot be determined."
            )

        scenarios = {
            "low": compute_scenario_uplift(peak_vehicles["low"], weight, baseline_flow),
            "base": compute_scenario_uplift(peak_vehicles["base"], weight, baseline_flow),
            "high": compute_scenario_uplift(peak_vehicles["high"], weight, baseline_flow),
        }

        conf_interval = [
            scenarios["low"]["uplift_vehicles"],
            scenarios["high"]["uplift_vehicles"],
        ]

        junction_results.append({
            "junction_id": inter.id,
            "junction_name": inter.name,
            "junction_code": inter.code,
            "distance_km": round(dist, 2),
            "spatial_weight": round(weight, 4),
            "baseline_flow": baseline_flow,
            "baseline_status": baseline_status,
            "baseline_note": baseline_note,
            "scenarios": scenarios,
            "confidence_interval": conf_interval,
        })

    doc_str = (
        "Parametric heuristic model estimating additional peak vehicular arrivals generated by planned events. "
        "Vehicle volumes are modeled as Attendance * (Mode Share / Vehicle Occupancy) * Peak Arrival Share, "
        "and distributed spatially across the k nearest physical intersections via an inverse-square gravity decay. "
        "All values represent deterministic scenario estimations, NOT trained machine learning predictions."
    )

    return {
        "event_name": name,
        "starts_at": starts_at,
        "expected_attendance": expected_attendance,
        "provenance": "parametric-heuristic",
        "model_type": "parametric-heuristic",
        "documentation": doc_str,
        "total_peak_vehicles": peak_vehicles,
        "assumptions": ASSUMPTION_DEFINITIONS,
        "junctions": junction_results,
    }
