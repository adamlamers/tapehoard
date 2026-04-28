# TapeHoard Justfile
# Install `just` to run these commands easily (e.g. `brew install just` or `cargo install just`)

set shell := ["bash", "-c"]

default:
    @just --list

# --- Development ---

# Run both the FastAPI backend and Svelte frontend in development mode
dev: db-upgrade
    @echo "Starting Backend (FastAPI) and Frontend (SvelteKit)..."
    @trap 'kill %1' SIGINT; \
        (cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --reload) & \
        (cd frontend && VITE_API_URL=http://localhost:${PORT:-8000} npm run dev)

# Run just the backend
backend: db-upgrade
    cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --reload

# Run just the frontend
frontend:
    cd frontend && npm run dev

# --- Quality Control ---

# Run all linters and type checkers (Ruff, ty, Svelte Check)
lint:
    @echo "Linting Python (Ruff)..."
    cd backend && uv run ruff check .
    @echo "Type checking Python (ty)..."
    cd backend && uv run ty check
    @echo "Type checking Svelte..."
    cd frontend && npm run check

# Run all backend tests
pytest:
    @echo "Running backend tests..."
    cd backend && uv run pytest

# Auto-format all code (Ruff Format)
format:
    @echo "Formatting Python (Ruff)..."
    cd backend && uv run ruff format .

# --- Database ---

# Apply all pending Alembic database migrations
db-upgrade:
    @echo "Upgrading Database..."
    cd backend && uv run alembic upgrade head

# Autogenerate a new migration (Usage: just db-migrate "message")
db-migrate message:
    @echo "Generating Migration..."
    cd backend && uv run alembic revision --autogenerate -m "{{message}}"

# --- Code Generation ---

# Generate the TypeScript API client from the FastAPI OpenAPI spec
generate-client:
    @echo "Generating TypeScript API client..."
    # Ensure backend is running first: `just backend`
    cd frontend && npx @hey-api/openapi-ts -i http://localhost:8000/openapi.json -o src/lib/api -c @hey-api/client-fetch

# --- Docker ---

# Build the production Docker image
docker-build:
    @echo "Building TapeHoard Docker image..."
    docker build -t tapehoard:latest -f docker/Dockerfile .

# Start the production stack using Docker Compose
docker-up:
    @echo "Starting TapeHoard stack..."
    cd docker && docker-compose up -d

# Stop the production stack
docker-down:
    @echo "Stopping TapeHoard stack..."
    cd docker && docker-compose down
