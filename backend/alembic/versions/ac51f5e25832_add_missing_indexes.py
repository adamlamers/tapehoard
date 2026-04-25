"""add_missing_indexes

Revision ID: ac51f5e25832
Revises: 38cb9df7a18c
Create Date: 2026-04-23 23:00:00.000000

"""

from typing import Sequence, Union
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "ac51f5e25832"
down_revision: Union[str, Sequence[str], None] = "38cb9df7a18c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_file_versions_filesystem_state_id", "file_versions", ["filesystem_state_id"]
    )
    op.create_index(
        "ix_restore_cart_filesystem_state_id", "restore_cart", ["filesystem_state_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_restore_cart_filesystem_state_id", table_name="restore_cart")
    op.drop_index("ix_file_versions_filesystem_state_id", table_name="file_versions")
