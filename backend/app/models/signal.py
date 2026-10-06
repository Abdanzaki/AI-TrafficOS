"""Traffic signal hardware and phase timing models.

Defines Signal controller units and individual SignalPhase state intervals.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.intersection import Intersection


class Signal(Base):
    """Traffic signal controller unit installed at an intersection."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intersection_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("intersections.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(30),
        default="active",
        server_default="active",
        nullable=False,
        index=True,
    )  # active, inactive, maintenance, fault
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
        back_populates="signals",
    )
    phases: Mapped[list["SignalPhase"]] = relationship(
        "SignalPhase",
        back_populates="signal",
        cascade="all, delete-orphan",
    )


class SignalPhase(Base):
    """Represents a specific interval, state (red/yellow/green), and timing within a signal cycle."""

    __tablename__ = "signal_phases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("signals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    intersection_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("intersections.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    phase_order: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default="1",
        nullable=False,
    )
    duration_seconds: Mapped[int] = mapped_column(
        Integer,
        default=30,
        server_default="30",
        nullable=False,
    )
    state: Mapped[str] = mapped_column(
        String(20),
        default="red",
        server_default="red",
        nullable=False,
    )  # red, yellow, green
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=sa.true(),
        nullable=False,
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
    signal: Mapped["Signal"] = relationship("Signal", back_populates="phases")
    intersection: Mapped[Optional["Intersection"]] = relationship(
        "Intersection",
        back_populates="signal_phases",
    )
