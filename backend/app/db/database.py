import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Dependency mapping for FastAPI
# Using standard relative path, but easily overridden with env vars later
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///tapehoard.db")

# connect_args={"check_same_thread": False} is required for SQLite in FastAPI
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
