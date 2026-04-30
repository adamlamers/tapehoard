"""add_is_cancelled_to_jobs

Revision ID: 7f8e9d10c2a3
Revises: e851b23b0f5d
Create Date: 2026-04-30 15:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7f8e9d10c2a3"
down_revision: Union[str, Sequence[str], None] = "e851b23b0f5d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("is_cancelled", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("jobs", "is_cancelled")
