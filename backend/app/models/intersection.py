"""Intersection model module.

Defines the core physical intersection entities managed by AI TrafficOS.
Extended in Phase 2 with operational codes, status, and municipal zoning.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.ai import AIDecision, AIPrediction
    from app.models.event import Incident, VehicleEvent
    from app.models.road import Lane
    from app.models.signal import Signal, SignalPhase
    from app.models.traffic import TrafficRecord


class Intersection(Base):
    """Represents a physical road intersection monitored and managed by the OS."""

    __tablename__ = "intersections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(30),
        default="active",
        server_default="active",
        nullable=False,
        index=True,
    )  # active, inactive, maintenance
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    zone: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
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
    lanes: Mapped[list["Lane"]] = relationship(
        "Lane",
        back_populates="intersection",
    )
    signals: Mapped[list["Signal"]] = relationship(
        "Signal",
        back_populates="intersection",
        cascade="all, delete-orphan",
    )
    signal_phases: Mapped[list["SignalPhase"]] = relationship(
        "SignalPhase",
        back_populates="intersection",
    )
    vehicle_events: Mapped[list["VehicleEvent"]] = relationship(
        "VehicleEvent",
        back_populates="intersection",
    )
    incidents: Mapped[list["Incident"]] = relationship(
        "Incident",
        back_populates="intersection",
    )
    traffic_records: Mapped[list["TrafficRecord"]] = relationship(
        "TrafficRecord",
        back_populates="intersection",
    )
    ai_predictions: Mapped[list["AIPrediction"]] = relationship(
        "AIPrediction",
        back_populates="intersection",
    )
    ai_decisions: Mapped[list["AIDecision"]] = relationship(
        "AIDecision",
        back_populates="intersection",
    )
