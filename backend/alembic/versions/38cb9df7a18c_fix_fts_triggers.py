"""fix_fts_triggers

Revision ID: 38cb9df7a18c
Revises: 33d682d2c089
Create Date: 2026-04-23 21:50:00.000000

"""

from typing import Sequence, Union
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "38cb9df7a18c"
down_revision: Union[str, Sequence[str], None] = "33d682d2c089"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop old invalid triggers
    op.execute("DROP TRIGGER IF EXISTS fts_ai")
    op.execute("DROP TRIGGER IF EXISTS fts_ad")
    op.execute("DROP TRIGGER IF EXISTS fts_au")

    # Create correct triggers for standalone FTS5 table
    op.execute("""
        CREATE TRIGGER fts_ai AFTER INSERT ON filesystem_state BEGIN
            INSERT INTO filesystem_fts(rowid, file_path) VALUES (new.id, new.file_path);
        END;
    """)

    op.execute("""
        CREATE TRIGGER fts_ad AFTER DELETE ON filesystem_state BEGIN
            DELETE FROM filesystem_fts WHERE rowid = old.id;
        END;
    """)

    # Only update FTS if the file_path actually changes
    op.execute("""
        CREATE TRIGGER fts_au AFTER UPDATE OF file_path ON filesystem_state BEGIN
            UPDATE filesystem_fts SET file_path = new.file_path WHERE rowid = old.id;
        END;
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS fts_ai")
    op.execute("DROP TRIGGER IF EXISTS fts_ad")
    op.execute("DROP TRIGGER IF EXISTS fts_au")

    # Recreate the old (invalid but matches previous state) triggers if needed for rollback
    op.execute("""
        CREATE TRIGGER fts_ai AFTER INSERT ON filesystem_state BEGIN
            INSERT INTO filesystem_fts(rowid, file_path) VALUES (new.id, new.file_path);
        END;
    """)

    op.execute("""
        CREATE TRIGGER fts_ad AFTER DELETE ON filesystem_state BEGIN
            INSERT INTO filesystem_fts(filesystem_fts, rowid, file_path) VALUES('delete', old.id, old.file_path);
        END;
    """)

    op.execute("""
        CREATE TRIGGER fts_au AFTER UPDATE ON filesystem_state BEGIN
            INSERT INTO filesystem_fts(filesystem_fts, rowid, file_path) VALUES('delete', old.id, old.file_path);
            INSERT INTO filesystem_fts(rowid, file_path) VALUES (new.id, new.file_path);
        END;
    """)
