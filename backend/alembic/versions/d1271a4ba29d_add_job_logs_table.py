"""add_job_logs_table

Revision ID: d1271a4ba29d
Revises: ffdd68ee8ee3
Create Date: 2026-04-30 00:36:23.634265

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d1271a4ba29d"
down_revision: Union[str, Sequence[str], None] = "ffdd68ee8ee3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "job_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("jobs.id"), nullable=False),
        sa.Column("message", sa.String, nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.datetime("now"),
        ),
    )
    op.create_index("ix_job_logs_job_id", "job_logs", ["job_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_job_logs_job_id", "job_logs")
    op.drop_table("job_logs")
