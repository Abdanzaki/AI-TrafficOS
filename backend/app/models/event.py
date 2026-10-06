"""Placeholder models for Phase 4 (Computer Vision) and Phase 5 (Predictive AI).

Defines vehicle detection events and incident records.
Real ingestion, telemetry pipelines, and classification logic arrive in Phase 4 and Phase 5.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class VehicleEvent(Base):
    """Vehicle detection event placeholder. Concrete event processing arrives in Phase 4."""

    __tablename__ = "vehicle_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intersection_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("intersections.id", ondelete="CASCADE"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Incident(Base):
    """Traffic incident placeholder. Real incident detection arrives in Phase 4/5."""

    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intersection_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("intersections.id", ondelete="CASCADE"),
        nullable=True,
    )
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
