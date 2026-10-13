"""Traffic violation models module.

Defines computer vision detected traffic violations including red light runners,
wrong-way driving, and motorcycle rider helmet non-compliance.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.intersection import Intersection


class Violation(Base):
    """Traffic violation detected via computer vision heuristics and edge perception."""

    __tablename__ = "violations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    violation_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )  # red_light, wrong_way, no_helmet
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    intersection_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("intersections.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    camera_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )
    confidence: Mapped[float] = mapped_column(
        Float,
        default=1.0,
        nullable=False,
    )  # Bounded float [0.0, 1.0]
    status: Mapped[str] = mapped_column(
        String(30),
        default="recorded",
        server_default="recorded",
        nullable=False,
        index=True,
    )  # recorded, reviewed, dismissed, escalated
    evidence_ref: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )  # Snapshot file path or URL via storage.py
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )  # Diagnostic details: track_id, signal_phase, bbox, lane_id, head_crop_box, etc.
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
        back_populates="violations",
    )
