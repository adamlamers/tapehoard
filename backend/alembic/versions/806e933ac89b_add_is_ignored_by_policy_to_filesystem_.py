"""add is_ignored_by_policy to filesystem_state

Revision ID: 806e933ac89b
Revises: 349e61f9e856
Create Date: 2026-05-04 19:34:38.280865

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "806e933ac89b"
down_revision: Union[str, Sequence[str], None] = "349e61f9e856"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Check if column already exists (e.g. from manual migration)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("filesystem_state")]

    if "is_ignored_by_policy" not in columns:
        op.add_column(
            "filesystem_state",
            sa.Column(
                "is_ignored_by_policy", sa.Boolean(), nullable=False, server_default="0"
            ),
        )

    # Create index for efficient querying
    indexes = [idx["name"] for idx in inspector.get_indexes("filesystem_state")]
    if "ix_filesystem_state_is_ignored_by_policy" not in indexes:
        op.create_index(
            "ix_filesystem_state_is_ignored_by_policy",
            "filesystem_state",
            ["is_ignored_by_policy"],
            unique=False,
        )

    # Backfill: set is_ignored_by_policy = is_ignored for existing records
    op.execute("UPDATE filesystem_state SET is_ignored_by_policy = is_ignored")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_filesystem_state_is_ignored_by_policy", table_name="filesystem_state"
    )
    op.drop_column("filesystem_state", "is_ignored_by_policy")
