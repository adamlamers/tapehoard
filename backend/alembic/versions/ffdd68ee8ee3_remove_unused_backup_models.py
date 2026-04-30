"""remove_unused_backup_models

Revision ID: ffdd68ee8ee3
Revises: c2512c86348b
Create Date: 2026-04-29 22:32:01.544848

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ffdd68ee8ee3"
down_revision: Union[str, Sequence[str], None] = "c2512c86348b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_table("job_logs")
    op.drop_table("backups")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        "backups",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("job_name", sa.String(), nullable=False),
        sa.Column("job_type", sa.String(), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
    )
    op.create_table(
        "job_logs",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "backup_id", sa.Integer(), sa.ForeignKey("backups.id"), nullable=False
        ),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("log_level", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
    )
