"""add redundancy coverage

Revision ID: c2983e8729c5
Revises: c2512c86348b
Create Date: 2026-05-09 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2983e8729c5"
down_revision: Union[str, Sequence[str], None] = "734957a4e25f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "filesystem_state",
        sa.Column(
            "redundancy_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.create_table(
        "file_media_coverage",
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("media_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["file_id"], ["filesystem_state.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["media_id"], ["storage_media.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("file_id", "media_id"),
    )

    # Backfill from existing file_versions — only non-split complete copies
    # Include all media statuses (active, full, offline) as they all provide protection.
    # Failed/retired media should already have their file_versions purged.
    op.execute("""
        INSERT OR IGNORE INTO file_media_coverage (file_id, media_id)
        SELECT DISTINCT fv.filesystem_state_id, fv.media_id
        FROM file_versions fv
        JOIN storage_media sm ON sm.id = fv.media_id
        JOIN filesystem_state fs ON fs.id = fv.filesystem_state_id
        WHERE sm.status IN ('active', 'full', 'offline')
          AND fv.offset_start = 0
          AND fv.offset_end = fs.size
    """)

    op.execute("""
        UPDATE filesystem_state
        SET redundancy_count = (
            SELECT COUNT(*) FROM file_media_coverage
            WHERE file_media_coverage.file_id = filesystem_state.id
        )
    """)

    op.create_index(
        "idx_fs_redundancy",
        "filesystem_state",
        ["redundancy_count", "is_ignored", "is_deleted"],
    )

    op.execute("""
        CREATE TRIGGER trg_coverage_insert AFTER INSERT ON file_media_coverage
        BEGIN
            UPDATE filesystem_state
            SET redundancy_count = redundancy_count + 1
            WHERE id = NEW.file_id;
        END
    """)

    op.execute("""
        CREATE TRIGGER trg_coverage_delete AFTER DELETE ON file_media_coverage
        BEGIN
            UPDATE filesystem_state
            SET redundancy_count = redundancy_count - 1
            WHERE id = OLD.file_id;
        END
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_coverage_delete")
    op.execute("DROP TRIGGER IF EXISTS trg_coverage_insert")
    op.drop_index("idx_fs_redundancy", table_name="filesystem_state")
    op.drop_table("file_media_coverage")
    op.drop_column("filesystem_state", "redundancy_count")
