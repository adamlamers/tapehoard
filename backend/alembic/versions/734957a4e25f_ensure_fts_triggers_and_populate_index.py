"""ensure_fts_triggers_and_populate_index

Revision ID: 734957a4e25f
Revises: bbe2fb40a559
Create Date: 2026-05-07 22:04:12.654591

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "734957a4e25f"
down_revision: Union[str, Sequence[str], None] = "bbe2fb40a559"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Ensure FTS triggers exist and populate the FTS index with existing data.

    This migration fixes two issues:
    1. Triggers may be missing or broken in existing databases
    2. The FTS table may be empty or out of sync with filesystem_state
    """
    # Drop existing triggers if they exist (to ensure clean state)
    op.execute("DROP TRIGGER IF EXISTS fts_ai")
    op.execute("DROP TRIGGER IF EXISTS fts_ad")
    op.execute("DROP TRIGGER IF EXISTS fts_au")

    # Create correct triggers for standalone FTS5 table
    # Trigger: After Insert - add new row to FTS
    op.execute("""
        CREATE TRIGGER fts_ai
        AFTER INSERT ON filesystem_state
        BEGIN
            INSERT INTO filesystem_fts(rowid, file_path)
            VALUES (new.id, new.file_path);
        END;
    """)

    # Trigger: After Delete - remove row from FTS
    op.execute("""
        CREATE TRIGGER fts_ad
        AFTER DELETE ON filesystem_state
        BEGIN
            DELETE FROM filesystem_fts
            WHERE rowid = old.id;
        END;
    """)

    # Trigger: After Update - update row in FTS (only if file_path changed)
    op.execute("""
        CREATE TRIGGER fts_au
        AFTER UPDATE OF file_path ON filesystem_state
        BEGIN
            UPDATE filesystem_fts
            SET file_path = new.file_path
            WHERE rowid = old.id;
        END;
    """)

    # Clear existing FTS data (to avoid duplicates)
    op.execute("DELETE FROM filesystem_fts")

    # Populate FTS index with all existing filesystem_state data
    # This ensures search works for all existing files
    op.execute("""
        INSERT INTO filesystem_fts(rowid, file_path)
        SELECT id, file_path
        FROM filesystem_state
    """)


def downgrade() -> None:
    """
    Downgrade: Remove triggers and clear FTS index.

    Note: This will break search functionality until upgrade is re-run.
    """
    # Drop triggers
    op.execute("DROP TRIGGER IF EXISTS fts_ai")
    op.execute("DROP TRIGGER IF EXISTS fts_ad")
    op.execute("DROP TRIGGER IF EXISTS fts_au")

    # Clear FTS data
    op.execute("DELETE FROM filesystem_fts")
