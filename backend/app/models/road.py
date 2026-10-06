"""Road network and lane topology models.

Defines Road segments and individual Lane configurations.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.event import VehicleEvent
    from app.models.intersection import Intersection
    from app.models.traffic import TrafficRecord


class Road(Base):
    """Physical roadway segment classified by hierarchy and functional type."""

    __tablename__ = "roads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    road_type: Mapped[str] = mapped_column(String(50), nullable=False)  # arterial, collector, local
    speed_limit_kmh: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    geometry: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # GeoJSON / WKT representation
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
    lanes: Mapped[list["Lane"]] = relationship(
        "Lane",
        back_populates="road",
        cascade="all, delete-orphan",
    )


class Lane(Base):
    """Individual roadway lane with directional heading, channelization, and intersection association."""

    __tablename__ = "lanes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    road_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("roads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    intersection_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("intersections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    lane_number: Mapped[int] = mapped_column(Integer, nullable=False)
    direction: Mapped[str] = mapped_column(String(50), nullable=False)  # northbound, southbound, etc.
    lane_type: Mapped[str] = mapped_column(String(50), nullable=False)  # through, left_turn, right_turn, bus, bike
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
    road: Mapped["Road"] = relationship("Road", back_populates="lanes")
    intersection: Mapped[Optional["Intersection"]] = relationship(
        "Intersection",
        back_populates="lanes",
    )
    vehicle_events: Mapped[list["VehicleEvent"]] = relationship(
        "VehicleEvent",
        back_populates="lane",
    )
    traffic_records: Mapped[list["TrafficRecord"]] = relationship(
        "TrafficRecord",
        back_populates="lane",
    )
