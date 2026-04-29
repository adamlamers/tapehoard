"""remove is_indexed flag

Revision ID: 1b59e22b9b7a
Revises: fbbc0a40a840
Create Date: 2026-04-28 23:44:04.949304

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1b59e22b9b7a"
down_revision: Union[str, Sequence[str], None] = "fbbc0a40a840"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # We use batch_alter_table for SQLite compatibility
    with op.batch_alter_table("filesystem_state", schema=None) as batch_op:
        batch_op.drop_column("is_indexed")
        batch_op.alter_column(
            "size",
            existing_type=sa.INTEGER(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )

    with op.batch_alter_table("storage_media", schema=None) as batch_op:
        batch_op.alter_column(
            "capacity",
            existing_type=sa.INTEGER(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "bytes_used",
            existing_type=sa.INTEGER(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("storage_media", schema=None) as batch_op:
        batch_op.alter_column(
            "bytes_used",
            existing_type=sa.BigInteger(),
            type_=sa.INTEGER(),
            existing_nullable=False,
        )
        batch_op.alter_column(
            "capacity",
            existing_type=sa.BigInteger(),
            type_=sa.INTEGER(),
            existing_nullable=False,
        )

    with op.batch_alter_table("filesystem_state", schema=None) as batch_op:
        batch_op.alter_column(
            "size",
            existing_type=sa.BigInteger(),
            type_=sa.INTEGER(),
            existing_nullable=False,
        )
        batch_op.add_column(
            sa.Column(
                "is_indexed",
                sa.BOOLEAN(),
                server_default=sa.text("'0'"),
                nullable=False,
            )
        )
