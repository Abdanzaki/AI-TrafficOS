"""Synthetic traffic telemetry generator for model bootstrapping and testing."""

from datetime import timezone
from typing import Optional

import numpy as np
import pandas as pd


class SyntheticTrafficGenerator:
    """Generates synthetic traffic telemetry for model training when database records are insufficient.

    All generated rows carry source='synthetic' and match the traffic_records table schema
    plus an incident_active feature helper flag.
    """

    def __init__(self, seed: int = 42) -> None:
        """Initialize the synthetic traffic generator with a default random seed.

        Args:
            seed: Default random seed for reproducibility.
        """
        self.default_seed = seed

    def generate(
        self,
        intersection_ids: list[int],
        days: int,
        seed: Optional[int] = None,
    ) -> pd.DataFrame:
        """Generate 5-minute-interval synthetic traffic telemetry over N days.

        Produces realistic diurnal cycles with morning (8-10h) and evening (17-20h)
        Gaussian peak bumps, weekday vs weekend scaling, sensor noise, and rare
        incident anomalies with elevated congestion and reduced vehicle speed.

        Args:
            intersection_ids: List of unique intersection integer identifiers.
            days: Duration in days to simulate.
            seed: Random seed for this generation run (defaults to constructor seed if None or 42).

        Returns:
            DataFrame with columns matching traffic_records plus incident_active:
                - intersection_id (int)
                - lane_id (None)
                - recorded_at (tz-aware UTC datetime)
                - vehicle_count (int >= 0)
                - avg_speed_kmh (float)
                - congestion_level (int 0-100)
                - source ('synthetic')
                - incident_active (bool)
        """
        active_seed = self.default_seed if seed is None else seed
        rng = np.random.default_rng(active_seed)

        steps_per_day = 288  # 24 * 60 // 5
        total_steps = days * steps_per_day

        start_time = pd.Timestamp("2026-01-01 00:00:00", tz=timezone.utc)
        timestamps = pd.date_range(start=start_time, periods=total_steps, freq="5min", tz=timezone.utc)

        hours = timestamps.hour.to_numpy() + timestamps.minute.to_numpy() / 60.0
        dow = timestamps.dayofweek.to_numpy()
        is_weekend = dow >= 5
        weekend_scale = 0.65
        scale_factor = np.where(is_weekend, weekend_scale, 1.0)

        # Gaussian bumps: morning (8-10h, center ~8.75h) and evening (17-20h, center ~18.25h)
        morning_bump = 45.0 * np.exp(-((hours - 8.75) ** 2) / (2.0 * (0.9 ** 2)))
        evening_bump = 55.0 * np.exp(-((hours - 18.25) ** 2) / (2.0 * (1.1 ** 2)))

        records: list[pd.DataFrame] = []

        for intersection_id in intersection_ids:
            # Per-intersection baseline capacity and throughput
            base_volume = 20.0 + (int(intersection_id) % 7) * 5.0
            expected_volume = (base_volume + morning_bump + evening_bump) * scale_factor

            vol_noise = rng.normal(0.0, 3.0, size=total_steps)
            volume = np.maximum(0.0, np.round(expected_volume + vol_noise))
            vehicle_count = volume.astype(int)

            # Rare short incident spikes (lasting 15-30 minutes = 3-6 steps)
            incident_active = np.zeros(total_steps, dtype=bool)
            num_incidents = max(1, int(rng.poisson(days * 0.4)))
            for _ in range(num_incidents):
                if total_steps > 24:
                    idx = int(rng.integers(12, total_steps - 12))
                    dur = int(rng.integers(3, 7))
                    incident_active[idx : min(idx + dur, total_steps)] = True

            # Congestion level from volume over capacity plus noise
            capacity = 100.0 + (int(intersection_id) % 5) * 15.0
            cong_noise = rng.normal(0.0, 3.0, size=total_steps)
            raw_congestion = (volume / capacity) * 100.0 + cong_noise
            congestion = np.clip(np.round(raw_congestion), 0, 100).astype(int)

            # Incidents spike congestion to 80-98%
            incident_cong = rng.integers(80, 98, size=total_steps)
            congestion = np.where(incident_active, np.maximum(congestion, incident_cong), congestion)

            # Speed is inversely related to congestion with free-flow speed around 60 km/h
            speed_noise = rng.normal(0.0, 1.5, size=total_steps)
            speed = np.maximum(5.0, 60.0 * (1.0 - 0.75 * (congestion / 100.0)) + speed_noise)

            # Incidents drop speeds to 5-15 km/h
            incident_speed = rng.uniform(5.0, 15.0, size=total_steps)
            speed = np.where(incident_active, incident_speed, speed)
            avg_speed_kmh = np.round(speed, 2)

            df_intersection = pd.DataFrame({
                "intersection_id": int(intersection_id),
                "lane_id": None,
                "recorded_at": timestamps,
                "vehicle_count": vehicle_count,
                "avg_speed_kmh": avg_speed_kmh,
                "congestion_level": congestion,
                "source": "synthetic",
                "incident_active": incident_active,
            })
            records.append(df_intersection)

        if not records:
            return pd.DataFrame(columns=[
                "intersection_id",
                "lane_id",
                "recorded_at",
                "vehicle_count",
                "avg_speed_kmh",
                "congestion_level",
                "source",
                "incident_active",
            ])

        return pd.concat(records, ignore_index=True)
