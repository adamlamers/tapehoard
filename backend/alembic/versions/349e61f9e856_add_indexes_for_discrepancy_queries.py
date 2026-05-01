"""add_indexes_for_discrepancy_queries

Revision ID: 349e61f9e856
Revises: 7f8e9d10c2a3
Create Date: 2026-04-30 20:36:16.237463

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "349e61f9e856"
down_revision: Union[str, Sequence[str], None] = "7f8e9d10c2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(
        op.f("ix_filesystem_state_last_seen_timestamp"),
        "filesystem_state",
        ["last_seen_timestamp"],
        unique=False,
    )
    op.create_index(
        op.f("ix_filesystem_state_missing_acknowledged_at"),
        "filesystem_state",
        ["missing_acknowledged_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        op.f("ix_filesystem_state_missing_acknowledged_at"),
        table_name="filesystem_state",
    )
    op.drop_index(
        op.f("ix_filesystem_state_last_seen_timestamp"),
        table_name="filesystem_state",
    )
