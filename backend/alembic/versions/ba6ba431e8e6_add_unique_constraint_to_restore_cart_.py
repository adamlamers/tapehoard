"""add unique constraint to restore_cart filesystem_state_id

Revision ID: ba6ba431e8e6
Revises: c2983e8729c5
Create Date: 2026-05-11 00:36:23.649121

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "ba6ba431e8e6"
down_revision: Union[str, Sequence[str], None] = "c2983e8729c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite requires batch mode to add constraints (copy-and-move strategy)
    with op.batch_alter_table("restore_cart") as batch_op:
        batch_op.create_unique_constraint(
            "uq_restore_cart_file", ["filesystem_state_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("restore_cart") as batch_op:
        batch_op.drop_constraint("uq_restore_cart_file", type_="unique")
