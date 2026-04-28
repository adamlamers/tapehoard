import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from typing import Dict, Any

# Dependency mapping for FastAPI
# Using standard relative path, but easily overridden with env vars later
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///tapehoard.db")

# connect_args={"check_same_thread": False} is required for SQLite in FastAPI
engine_kwargs: Dict[str, Any] = {
    "connect_args": {"check_same_thread": False, "timeout": 30}
}

# For testing environment, we want immediate visibility across sessions
if (
    "mode=memory" in SQLALCHEMY_DATABASE_URL
    or SQLALCHEMY_DATABASE_URL == "sqlite:///:memory:"
):
    engine_kwargs["isolation_level"] = None

# Only apply pooling arguments for non-memory databases
if SQLALCHEMY_DATABASE_URL != "sqlite:///:memory:":
    engine_kwargs.update(
        {
            "pool_size": 20,
            "max_overflow": 10,
            "pool_timeout": 30,
        }
    )

engine = create_engine(SQLALCHEMY_DATABASE_URL, **engine_kwargs)


# Enable WAL mode for SQLite to allow concurrent reads and writes
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size=-20000")  # 20MB cache
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute(
        "PRAGMA mmap_size=30000000000"
    )  # Enable memory mapping for massive indexes
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
