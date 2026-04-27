import os
import tempfile

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from alembic import command

# Create a stable temporary file for the entire test session
db_fd, db_path = tempfile.mkstemp()
SQLALCHEMY_DATABASE_URL = f"sqlite:///{db_path}"

# CRITICAL: Force the application core to use our test engine and session BEFORE imports
os.environ["DATABASE_URL"] = SQLALCHEMY_DATABASE_URL

import app.db.database as db_module  # noqa: E402
from app.db.database import get_db  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.main import app  # noqa: E402

# Setup engine with aggressive busy timeout
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Patch the global db module
db_module.engine = engine
db_module.SessionLocal = TestingSessionLocal
db_module.SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    """Initializes the database schema using Alembic once per session."""
    # Run migrations
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_cfg = Config(os.path.join(base_dir, "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(base_dir, "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", SQLALCHEMY_DATABASE_URL)

    command.upgrade(alembic_cfg, "head")

    yield

    os.close(db_fd)
    if os.path.exists(db_path):
        os.remove(db_path)


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
                # Avoid truncating internal alembic or FTS tables
                if "alembic" not in table_name and "fts" not in table_name:
                    conn.execute(text(f"DELETE FROM {table_name}"))
            conn.execute(text("PRAGMA foreign_keys = ON"))


@pytest.fixture(scope="function")
def client(db_session):
    """Provides a TestClient with overridden DB dependency."""
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
