#!/bin/bash
set -e

echo "Starting TapeHoard..."

# Change to backend directory
cd /app/backend

# Run database migrations
echo "Running database migrations..."
uv run alembic upgrade head

# Start the application
echo "Starting application server..."
exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
