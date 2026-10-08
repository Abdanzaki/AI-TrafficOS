"""Add composite index on notifications for entity deduplication lookup.

Revision ID: 0006_notifications_dedupe_index
Revises: 0005_ml_model_registry
Create Date: 2026-10-08 12:00:00.000000
"""

from collections.abc import Sequence
from typing import Union

from alembic import op

# Revision identifiers, used by Alembic.
revision: str = "0006_notifications_dedupe_index"
down_revision: Union[str, None] = "0005_ml_model_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create composite index on notifications for fast entity deduplication."""
    op.create_index(
        "ix_notifications_entity_dedupe",
        "notifications",
        ["entity_type", "entity_id", "is_read", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Drop composite deduplication index from notifications."""
    op.drop_index("ix_notifications_entity_dedupe", table_name="notifications")
