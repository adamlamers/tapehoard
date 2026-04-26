#!/bin/bash
set -e

# Establish global environment safety
export HOME=/home/appuser
export PATH="/app/backend/.venv/bin:$PATH"
export PYTHONPATH="/app/backend"

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

    # Only chown the home directory (non-recursive)
    chown "$PUID:$PGID" /home/appuser

    echo "Dropping privileges to appuser..."
    exec setpriv --reuid="$PUID" --regid="$PGID" --init-groups "$0" "$@"
fi

# Change to backend directory
cd /app/backend

# Use the pre-built virtualenv directly for maximum speed and stability.
# This prevents UV from trying to sync or download tools at runtime.
echo "Running database migrations..."
alembic upgrade head

# Start the application
echo "Starting Archive Command server on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
