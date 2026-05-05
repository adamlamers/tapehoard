import os
import tempfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Use a file in /tmp for unit tests (avoids SQLite URI parsing quirks)
db_fd, db_path = tempfile.mkstemp(dir="/tmp", prefix="tapehoard_test_", suffix=".db")
SQLALCHEMY_DATABASE_URL = f"sqlite:///{db_path}"

# CRITICAL: Force the application core to use our test engine and session BEFORE imports
os.environ["DATABASE_URL"] = SQLALCHEMY_DATABASE_URL

import app.db.database as db_module  # noqa: E402
from app.db.database import get_db  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.main import app  # noqa: E402

# Setup engine with a file-based SQLite in /tmp for reliable shared access
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Patch the global db module
db_module.engine = engine
db_module.SessionLocal = TestingSessionLocal
db_module.SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL

# Patch SessionLocal in all modules that imported it before we could patch db_module
import app.services.scanner as scanner_module  # noqa: E402
import app.services.scheduler as scheduler_module  # noqa: E402
import app.services.notifications as notifications_module  # noqa: E402

scanner_module.SessionLocal = TestingSessionLocal
scheduler_module.SessionLocal = TestingSessionLocal
notifications_module.SessionLocal = TestingSessionLocal


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Initializes the database schema using Alembic once per session."""
    from alembic import command
    from alembic.config import Config

    # Run migrations using the SAME connection as the test engine
    # so the shared database is visible to tests

    # Keep the connection open for the entire session
    conn = engine.connect()
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_cfg = Config(os.path.join(base_dir, "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(base_dir, "alembic"))
    alembic_cfg.attributes["connection"] = conn

    with conn.begin():
        command.upgrade(alembic_cfg, "head")

    yield

    conn.close()
    os.close(db_fd)
    for suffix in ("", "-shm", "-wal"):
        p = db_path + suffix
        if os.path.exists(p):
            os.remove(p)


@pytest.fixture(scope="function")
def db_session():
    """Creates a new database session and performs a clean truncation after every test."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        # Atomic truncation using raw SQL
        with engine.begin() as conn:
            conn.execute(text("PRAGMA foreign_keys = OFF"))
            # Fetch all tables from the metadata
            for table_name in reversed(Base.metadata.tables.keys()):
                # Avoid truncating internal alembic tables
                if "alembic" not in table_name:
                    conn.execute(text(f"DELETE FROM {table_name}"))
            # FTS5 virtual table is not in Base.metadata; clear it explicitly
            conn.execute(text("DELETE FROM filesystem_fts"))
            conn.execute(text("PRAGMA foreign_keys = ON"))


@pytest.fixture(scope="function")
def client(db_session):
    """Provides a TestClient with overridden DB dependency."""
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
