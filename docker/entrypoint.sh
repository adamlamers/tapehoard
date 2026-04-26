#!/bin/bash
set -e

# Establish global UV safety
export HOME=/home/appuser
export UV_CACHE_DIR=/uv-cache
export UV_CONFIG_DIR=/uv-cache/config
export UV_DATA_DIR=/uv-cache/data

echo "Starting TapeHoard: Archive Command..."

# Handle PUID/PGID without recursive chown
if [ "$(id -u)" = '0' ] && [ -n "$PUID" ] && [ -n "$PGID" ]; then
    echo "Syncing system user identity to PUID:PGID $PUID:$PGID..."

    # Configure the group
    if ! getent group appuser >/dev/null; then
        groupadd -g "$PGID" appuser
    else
        groupmod -g "$PGID" appuser
    fi

    # Configure the user
    if ! getent passwd appuser >/dev/null; then
        useradd -m -d /home/appuser -u "$PUID" -g "$PGID" -s /bin/bash appuser
    else
        usermod -u "$PUID" -g "$PGID" appuser
    fi

    # Only chown the home directory and cache if needed (non-recursive)
    # We rely on the user to have set correct permissions on external volumes
    # like /database, /staging, and /source_data.
    chown "$PUID:$PGID" /home/appuser /uv-cache

    echo "Dropping privileges to appuser..."
    exec setpriv --reuid="$PUID" --regid="$PGID" --init-groups "$0" "$@"
fi

# Change to backend directory
cd /app/backend

# Use UV for all operations
# Note: /app/backend is kept as root-owned/read-only for security and speed.
echo "Running database migrations..."
uv --cache-dir /uv-cache run alembic upgrade head

# Start the application
echo "Starting Archive Command server on port ${PORT:-8000}..."
exec uv --cache-dir /uv-cache run uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
