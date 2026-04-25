"""add_path_index

Revision ID: 51c095df4615
Revises: ac51f5e25832
Create Date: 2026-04-25 22:15:00.000000

"""

from typing import Sequence, Union
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "51c095df4615"
down_revision: Union[str, Sequence[str], None] = "ac51f5e25832"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add index on file_path to speed up directory prefix matching
    op.create_index("ix_filesystem_state_file_path", "filesystem_state", ["file_path"])


def downgrade() -> None:
    op.drop_index("ix_filesystem_state_file_path", table_name="filesystem_state")
