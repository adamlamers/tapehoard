#!/bin/bash
set -e

# Establish global UV safety
export HOME=/home/appuser
export UV_CACHE_DIR=/uv-cache
export UV_CONFIG_DIR=/uv-cache/config
export UV_DATA_DIR=/uv-cache/data

echo "Starting TapeHoard..."

# Handle PUID/PGID for volume permissions
if [ "$(id -u)" = '0' ] && [ -n "$PUID" ] && [ -n "$PGID" ]; then
    echo "Adjusting permissions for PUID:PGID $PUID:$PGID..."

    groupmod -g "$PGID" appuser 2>/dev/null || groupadd -g "$PGID" appuser
    usermod -u "$PUID" -g "$PGID" -d /home/appuser appuser 2>/dev/null || useradd -m -d /home/appuser -u "$PUID" -g "$PGID" -s /bin/bash appuser

    # Ensure all volumes are writable by the mapped user
    chown -R "$PUID:$PGID" /database /staging /restores /app/backend /home/appuser /uv-cache

    echo "Switching to appuser..."
    exec setpriv --reuid="$PUID" --regid="$PGID" --init-groups "$0" "$@"
fi

# Change to backend directory
cd /app/backend

# Use UV for all operations
echo "Running database migrations..."
uv --cache-dir /uv-cache run alembic upgrade head

# Start the application
echo "Starting application server on port ${PORT:-8000}..."
exec uv --cache-dir /uv-cache run uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
