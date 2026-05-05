"""add_secret_reference_columns

Revision ID: bbe2fb40a559
Revises: 6a15f2e5b03b
Create Date: 2026-05-05 08:35:21.154584

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "bbe2fb40a559"
down_revision: Union[str, Sequence[str], None] = "6a15f2e5b03b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "storage_media", sa.Column("secret_access_key_name", sa.String(), nullable=True)
    )
    op.add_column(
        "storage_media", sa.Column("encryption_secret_name", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("storage_media", "encryption_secret_name")
    op.drop_column("storage_media", "secret_access_key_name")
