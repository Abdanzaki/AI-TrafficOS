"""Perception and incident event models.

Defines computer vision VehicleEvent detections and Incident occurrences.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.auth import User
    from app.models.emergency import EmergencyEvent
    from app.models.intersection import Intersection
    from app.models.road import Lane


class VehicleEvent(Base):
    """Computer vision vehicle detection event captured at an intersection and lane."""

    __tablename__ = "vehicle_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intersection_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("intersections.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    lane_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("lanes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    vehicle_type: Mapped[str] = mapped_column(
        String(50),
        default="car",
        server_default="car",
        nullable=False,
    )  # car, truck, bus, motorcycle, bicycle
    speed_kmh: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    direction: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
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
    intersection: Mapped[Optional["Intersection"]] = relationship(
        "Intersection",
        back_populates="vehicle_events",
    )
    lane: Mapped[Optional["Lane"]] = relationship(
        "Lane",
        back_populates="vehicle_events",
    )


class Incident(Base):
    """Traffic incident, collision, hazard, or road blockage."""

    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intersection_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("intersections.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="unknown",
        server_default="unknown",
        index=True,
    )  # low, medium, high, critical, unknown
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="reported",
        server_default="reported",
        index=True,
    )  # reported, acknowledged, resolved
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    reported_by: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
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
    intersection: Mapped[Optional["Intersection"]] = relationship(
        "Intersection",
        back_populates="incidents",
    )
    reporter: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="reported_incidents",
    )
    emergency_events: Mapped[list["EmergencyEvent"]] = relationship(
        "EmergencyEvent",
        back_populates="incident",
    )
