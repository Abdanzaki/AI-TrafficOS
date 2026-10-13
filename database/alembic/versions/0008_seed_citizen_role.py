"""Seed citizen role for public traffic assistant and citizen RBAC.

Revision ID: 0008_seed_citizen_role
Revises: 0007_violations_table
Create Date: 2026-10-13 18:30:00.000000
"""

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Union

from alembic import op
import sqlalchemy as sa

# Revision identifiers, used by Alembic.
revision: str = "0008_seed_citizen_role"
down_revision: Union[str, None] = "0007_violations_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Insert citizen role into roles table if not already present."""
    now_utc = datetime.now(timezone.utc)
    roles_table = sa.table(
        "roles",
        sa.column("id", sa.Integer),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    # Check existing role or insert
    bind = op.get_bind()
    existing = bind.execute(
        sa.text("SELECT id FROM roles WHERE name = 'citizen'")
    ).fetchone()
    if not existing:
        op.bulk_insert(
            roles_table,
            [
                {
                    "name": "citizen",
                    "description": "Public citizen user with read-only access to public traffic information and reporting",
                    "created_at": now_utc,
                    "updated_at": now_utc,
                }
            ],
        )


def downgrade() -> None:
    """Remove citizen role."""
    op.execute(sa.text("DELETE FROM roles WHERE name = 'citizen'"))
