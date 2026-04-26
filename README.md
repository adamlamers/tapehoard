# TapeHoard

A robust, index-driven Tape Backup Manager designed for single-tape drive users and scalable to tape libraries.

For full architectural details, see [PLAN.md](PLAN.md).

## Docker Deployment

TapeHoard is designed to run as a Docker container with native hardware access.

### Permissions (PUID/PGID)
The container supports `PUID` and `PGID` environment variables to ensure files written to volumes match your host user's identity.

**Critical:** To ensure fast startup times, TapeHoard **does not** perform a recursive `chown` on your data. You must ensure your host directories are owned by the same PUID/PGID you provide to the container:

```bash
# Example: If PUID=1000 and PGID=1000
sudo chown -R 1000:1000 ./db ./staging ./source_data ./restores
```

### Example `docker-compose.yml`

```yaml
services:
  tapehoard:
    image: tapehoard:latest
    container_name: tapehoard
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=UTC
    volumes:
      - ./db:/database
      - ./staging:/staging
      - /mnt/my_data:/source_data:ro
      - /mnt/restores:/restores
      # LTO Tape Drive Passthrough
      - /dev/nst0:/dev/nst0
      - /dev/sgX:/dev/sgX
    devices:
      - /dev/nst0:/dev/nst0
      - /dev/sgX:/dev/sgX
    ports:
      - "8000:8000"
    restart: unless-stopped
```

## Project Structure

*   `backend/`: Python/FastAPI application handling the heavy lifting (hashing, streaming, db indexing).
*   `frontend/`: Svelte 5 application providing the Web UI.
*   `docker/`: Files required for building the multi-stage Docker container.
*   `docs/`: Additional documentation.

## Quickstart

(Coming soon)
