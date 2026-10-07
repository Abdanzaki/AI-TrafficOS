"""Create ml_models table for machine learning model registry.

Revision ID: 0005_ml_model_registry
Revises: 0004_signal_observations
Create Date: 2026-10-07 12:45:00.000000
"""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "0005_ml_model_registry"
down_revision: Union[str, None] = "0004_signal_observations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create ml_models table with constraints and indexes."""
    op.create_table(
        "ml_models",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("artifact_path", sa.Text(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("data_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("feature_names", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("horizon_steps", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_ml_models_name_version"),
    )

    op.create_index(
        "ix_ml_models_name",
        "ml_models",
        ["name"],
        unique=False,
    )


def downgrade() -> None:
    """Drop ml_models table and associated indexes."""
    op.drop_index("ix_ml_models_name", table_name="ml_models")
    op.drop_table("ml_models")
