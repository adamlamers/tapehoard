"""add_fts_table

Revision ID: 193bb204c677
Revises: 9a6e70fabf7b
Create Date: 2026-04-23 19:04:51.158603

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "193bb204c677"
down_revision: Union[str, Sequence[str], None] = "9a6e70fabf7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE VIRTUAL TABLE filesystem_fts USING fts5(
            file_path,
            tokenize='trigram'
        )
    """)

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


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS fts_ai")
    op.execute("DROP TRIGGER IF EXISTS fts_ad")
    op.execute("DROP TRIGGER IF EXISTS fts_au")
    op.execute("DROP TABLE IF EXISTS filesystem_fts")
