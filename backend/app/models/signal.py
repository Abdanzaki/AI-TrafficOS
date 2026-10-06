"""Placeholder — real signal control logic arrives in Phase 6."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SignalPhase(Base):
    """Placeholder model for traffic signal phases. Real signal control logic arrives in Phase 6."""

    __tablename__ = "signal_phases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intersection_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("intersections.id", ondelete="CASCADE"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
