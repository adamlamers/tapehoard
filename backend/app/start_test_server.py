"""
Test server startup script.
Runs Alembic migrations and starts Uvicorn in the SAME process,
so that in-memory SQLite works correctly for E2E tests.
"""

import os


def main() -> None:
    """Run migrations, then start the server in the same process."""
    # --- Step 1: Run Alembic migrations ---
    from alembic.config import Config
    from alembic import command

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_cfg = Config(os.path.join(base_dir, "alembic.ini"))
    alembic_cfg.set_main_option("script_location", os.path.join(base_dir, "alembic"))
    alembic_cfg.set_main_option(
        "sqlalchemy.url",
        os.environ.get("DATABASE_URL", "sqlite:///tapehoard.db"),
    )

    print("Running Alembic migrations...")
    command.upgrade(alembic_cfg, "head")
    print("Migrations complete.")

    # --- Step 2: Start Uvicorn ---
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8001"))

    print(f"Starting Uvicorn on {host}:{port}...")
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        workers=1,
        reload=False,
        log_level=os.environ.get("LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
