"""add structured location and type-specific fields to storage_media

Revision ID: 6a15f2e5b03b
Revises: 806e933ac89b
Create Date: 2026-05-05 01:07:03.581293

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "6a15f2e5b03b"
down_revision: Union[str, Sequence[str], None] = "806e933ac89b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("storage_media", schema=None) as batch_op:
        batch_op.add_column(sa.Column("location_building", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("location_room", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("location_rack", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("location_slot", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("generation", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("worm", sa.Boolean(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(
            sa.Column(
                "write_protected",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "compression", sa.Boolean(), nullable=False, server_default=sa.text("1")
            )
        )
        batch_op.add_column(sa.Column("encryption_key_id", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "cleaning_cartridge",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.add_column(sa.Column("drive_model", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("device_uuid", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "is_ssd", sa.Boolean(), nullable=False, server_default=sa.text("0")
            )
        )
        batch_op.add_column(sa.Column("mount_path", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("filesystem_type", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("connection_interface", sa.String(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "encrypted", sa.Boolean(), nullable=False, server_default=sa.text("0")
            )
        )
        batch_op.add_column(sa.Column("provider_template", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("endpoint_url", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("region", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("bucket_name", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("access_key_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("secret_access_key", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "path_style_access",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.add_column(sa.Column("storage_class", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "max_part_size_mb",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("5000"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "obfuscate_filenames",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.add_column(
            sa.Column("client_side_encryption_passphrase", sa.String(), nullable=True)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("storage_media", schema=None) as batch_op:
        batch_op.drop_column("client_side_encryption_passphrase")
        batch_op.drop_column("obfuscate_filenames")
        batch_op.drop_column("max_part_size_mb")
        batch_op.drop_column("storage_class")
        batch_op.drop_column("path_style_access")
        batch_op.drop_column("secret_access_key")
        batch_op.drop_column("access_key_id")
        batch_op.drop_column("bucket_name")
        batch_op.drop_column("region")
        batch_op.drop_column("endpoint_url")
        batch_op.drop_column("provider_template")
        batch_op.drop_column("encrypted")
        batch_op.drop_column("connection_interface")
        batch_op.drop_column("filesystem_type")
        batch_op.drop_column("mount_path")
        batch_op.drop_column("is_ssd")
        batch_op.drop_column("device_uuid")
        batch_op.drop_column("drive_model")
        batch_op.drop_column("cleaning_cartridge")
        batch_op.drop_column("encryption_key_id")
        batch_op.drop_column("compression")
        batch_op.drop_column("write_protected")
        batch_op.drop_column("worm")
        batch_op.drop_column("generation")
        batch_op.drop_column("location_slot")
        batch_op.drop_column("location_rack")
        batch_op.drop_column("location_room")
        batch_op.drop_column("location_building")
