"""add_missing_acknowledged_at

Revision ID: e851b23b0f5d
Revises: d1271a4ba29d
Create Date: 2026-04-30 12:42:04.671251

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e851b23b0f5d"
down_revision: Union[str, Sequence[str], None] = "d1271a4ba29d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "filesystem_state",
        sa.Column("missing_acknowledged_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("filesystem_state", "missing_acknowledged_at")
