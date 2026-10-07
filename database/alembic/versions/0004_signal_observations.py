"""Add CV optical observation fields to signals table.

Revision ID: 0004_signal_observations
Revises: 0003_phase3_road_graph
Create Date: 2026-10-07 05:50:00.000000
"""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa

# Revision identifiers, used by Alembic.
revision: str = "0004_signal_observations"
down_revision: Union[str, None] = "0003_phase3_road_graph"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add camera observation fields to signals table."""
    op.add_column("signals", sa.Column("observed_state", sa.String(length=20), nullable=True))
    op.add_column("signals", sa.Column("observed_confidence", sa.Float(), nullable=True))
    op.add_column("signals", sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index(
        "ix_signals_observed_state",
        "signals",
        ["observed_state"],
        unique=False,
    )


def downgrade() -> None:
    """Revert camera observation fields from signals table."""
    op.drop_index("ix_signals_observed_state", table_name="signals")
    op.drop_column("signals", "observed_at")
    op.drop_column("signals", "observed_confidence")
    op.drop_column("signals", "observed_state")
