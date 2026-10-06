"""Initial schema migration for Phase 1.

Revision ID: 0001
Revises: None
Create Date: 2026-10-06 00:00:00.000000
"""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa

# Revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create initial tables: intersections, signal_phases, vehicle_events, incidents."""
    # 1. intersections table
    op.create_table(
        "intersections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lon", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_intersections_name",
        "intersections",
        ["name"],
        unique=False,
    )

    # 2. signal_phases table (Phase 6 placeholder)
    op.create_table(
        "signal_phases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("intersection_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["intersection_id"],
            ["intersections.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # 3. vehicle_events table (Phase 4 placeholder)
    op.create_table(
        "vehicle_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("intersection_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["intersection_id"],
            ["intersections.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # 4. incidents table (Phase 4/5 placeholder)
    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("intersection_id", sa.Integer(), nullable=True),
        sa.Column(
            "severity",
            sa.String(length=20),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["intersection_id"],
            ["intersections.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    """Drop initial tables in reverse dependency order."""
    op.drop_table("incidents")
    op.drop_table("vehicle_events")
    op.drop_table("signal_phases")
    op.drop_index("ix_intersections_name", table_name="intersections")
    op.drop_table("intersections")
