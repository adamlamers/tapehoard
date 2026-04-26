#!/bin/bash
set -e

# Identify current user
USER_ID=$(id -u)

echo "Starting TapeHoard: Archive Command..."

# Decide if we should drop privileges
# We drop privileges ONLY if:
# 1. We are currently root (USER_ID 0)
# 2. PUID/PGID are provided and PUID is NOT 0
# 3. RUN_AS_ROOT is NOT set to true
if [ "$USER_ID" = '0' ] && [ -n "$PUID" ] && [ "$PUID" != "0" ] && [ "$RUN_AS_ROOT" != "true" ]; then
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

    # Ensure home directory exists and is owned correctly
    mkdir -p /home/appuser
    chown "$PUID:$PGID" /home/appuser

    echo "Dropping privileges to appuser..."
    export HOME=/home/appuser
    exec setpriv --reuid="$PUID" --regid="$PGID" --init-groups "$0" "$@"
fi

# If we are here, we are running as the current user (Root or Container-specified user)
if [ "$(id -u)" = '0' ]; then
    echo "Running as ROOT (Hardware Access Mode Enabled)"
    export HOME=/root
else
    echo "Running as UID $(id -u)"
    export HOME=/tmp
fi

# Establish environment
export PATH="/app/backend/.venv/bin:$PATH"
export PYTHONPATH="/app/backend"

# Change to backend directory
cd /app/backend

echo "Running database migrations..."
alembic upgrade head

# Start the application
echo "Starting Archive Command server on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
