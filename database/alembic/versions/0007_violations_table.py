"""Create violations table for CV-based traffic violation detection.

Revision ID: 0007_violations_table
Revises: 0006_notifications_dedupe_index
Create Date: 2026-10-13 15:00:00.000000
"""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers, used by Alembic.
revision: str = "0007_violations_table"
down_revision: Union[str, None] = "0006_notifications_dedupe_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create violations table and its operational indices."""
    op.create_table(
        "violations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("violation_type", sa.String(length=50), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "intersection_id",
            sa.Integer(),
            sa.ForeignKey("intersections.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("camera_id", sa.String(length=100), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="recorded",
        ),
        sa.Column("evidence_ref", sa.String(length=500), nullable=True),
        sa.Column(
            "details",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_violations_violation_type",
        "violations",
        ["violation_type"],
        unique=False,
    )
    op.create_index(
        "ix_violations_detected_at",
        "violations",
        ["detected_at"],
        unique=False,
    )
    op.create_index(
        "ix_violations_intersection_id",
        "violations",
        ["intersection_id"],
        unique=False,
    )
    op.create_index(
        "ix_violations_camera_id",
        "violations",
        ["camera_id"],
        unique=False,
    )
    op.create_index(
        "ix_violations_status",
        "violations",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_violations_created_at",
        "violations",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop violations table and indices."""
    op.drop_index("ix_violations_created_at", table_name="violations")
    op.drop_index("ix_violations_status", table_name="violations")
    op.drop_index("ix_violations_camera_id", table_name="violations")
    op.drop_index("ix_violations_intersection_id", table_name="violations")
    op.drop_index("ix_violations_detected_at", table_name="violations")
    op.drop_index("ix_violations_violation_type", table_name="violations")
    op.drop_table("violations")
