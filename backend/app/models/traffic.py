"""Traffic telemetry and aggregated sensor records.

Captures localized traffic flow rates, vehicular counts, and congestion index levels.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.intersection import Intersection
    from app.models.road import Lane


class TrafficRecord(Base):
    """Aggregated traffic observation recorded by sensor, camera, or algorithmic pipeline."""

    __tablename__ = "traffic_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intersection_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("intersections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    lane_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("lanes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    vehicle_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    avg_speed_kmh: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    congestion_level: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )  # 0 to 100 percentage scale
    source: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="sensor",
        server_default="sensor",
    )  # sensor, camera, manual, ai
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    intersection: Mapped["Intersection"] = relationship(
        "Intersection",
        back_populates="traffic_records",
    )
    lane: Mapped[Optional["Lane"]] = relationship(
        "Lane",
        back_populates="traffic_records",
    )
