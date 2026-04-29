"""add_is_deleted_to_filesystem_state

Revision ID: c2512c86348b
Revises: 1b59e22b9b7a
Create Date: 2026-04-29 17:40:08.079413

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2512c86348b"
down_revision: Union[str, Sequence[str], None] = "1b59e22b9b7a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "filesystem_state",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("filesystem_state", "is_deleted")
