"""Machine learning model registry SQLAlchemy model.

Stores catalog records of trained traffic forecasting models with version identifiers,
file artifact paths, out-of-sample evaluation metrics, and training data summaries.
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MLModel(Base):
    """Machine learning model registry cataloging trained forecasters and artifacts."""

    __tablename__ = "ml_models"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_ml_models_name_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    data_summary: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    feature_names: Mapped[Optional[list[Any]]] = mapped_column(JSONB, nullable=True)
    horizon_steps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
