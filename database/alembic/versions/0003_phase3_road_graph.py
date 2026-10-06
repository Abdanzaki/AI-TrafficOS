"""Phase 3 road graph topology migration.

Revision ID: 0003_phase3_road_graph
Revises: 0002
Create Date: 2026-10-06 18:30:00.000000
"""

from collections.abc import Sequence
from typing import Union

from alembic import op
import sqlalchemy as sa

# Revision identifiers, used by Alembic.
revision: str = "0003_phase3_road_graph"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add junction endpoints and physical routing properties to roads table."""
    op.add_column("roads", sa.Column("from_intersection_id", sa.Integer(), nullable=True))
    op.add_column("roads", sa.Column("to_intersection_id", sa.Integer(), nullable=True))
    op.add_column("roads", sa.Column("length_km", sa.Float(), nullable=True))
    op.add_column("roads", sa.Column("capacity_veh_per_hr", sa.Integer(), nullable=True))
    op.add_column(
        "roads",
        sa.Column("is_bidirectional", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )

    op.create_foreign_key(
        "fk_roads_from_intersection_id",
        "roads",
        "intersections",
        ["from_intersection_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_roads_to_intersection_id",
        "roads",
        "intersections",
        ["to_intersection_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index(
        "ix_roads_from_intersection_id",
        "roads",
        ["from_intersection_id"],
        unique=False,
    )
    op.create_index(
        "ix_roads_to_intersection_id",
        "roads",
        ["to_intersection_id"],
        unique=False,
    )


def downgrade() -> None:
    """Revert Phase 3 road graph topology additions in reverse order."""
    op.drop_index("ix_roads_to_intersection_id", table_name="roads")
    op.drop_index("ix_roads_from_intersection_id", table_name="roads")
    op.drop_constraint("fk_roads_to_intersection_id", "roads", type_="foreignkey")
    op.drop_constraint("fk_roads_from_intersection_id", "roads", type_="foreignkey")
    op.drop_column("roads", "is_bidirectional")
    op.drop_column("roads", "capacity_veh_per_hr")
    op.drop_column("roads", "length_km")
    op.drop_column("roads", "to_intersection_id")
    op.drop_column("roads", "from_intersection_id")
