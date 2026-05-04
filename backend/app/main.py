import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger

from app.api import archive, backups, inventory, restores, system


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Handles startup and shutdown events for the FastAPI application."""
    from app.services.scheduler import scheduler_manager

    logger.info("Initializing TapeHoard: Backup Manager...")
    scheduler_manager.start()
    yield
    logger.info("Shutting down Archive Command...")
    scheduler_manager.stop()


app = FastAPI(
    title="TapeHoard: Backup Manager",
    description="Index-driven archival station for LTO, HDD, and Cloud.",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure Cross-Origin Resource Sharing (CORS)
# Use TAPEHOARD_CORS_ORIGINS env var (comma-separated) in production
# Default allows all origins (*), but explicitly add localhost:5174 for Playwright tests
cors_default = "*,http://localhost:5174,http://localhost:5173"
cors_origins = os.getenv("TAPEHOARD_CORS_ORIGINS", cors_default).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in cors_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(system.router)
app.include_router(inventory.router)
app.include_router(archive.router)
app.include_router(backups.router)
app.include_router(restores.router)

# --- Frontend Static File Serving ---

# Dynamically resolve the static folder path relative to this file
base_source_dir = os.path.dirname(os.path.abspath(__file__))
static_assets_path = os.path.join(os.path.dirname(base_source_dir), "static")

if os.path.exists(static_assets_path):
    logger.info(f"Mounting static assets from: {static_assets_path}")
    app.mount("/", StaticFiles(directory=static_assets_path, html=True), name="static")

    @app.exception_handler(404)
    async def spa_catch_all_handler(request_object, exception_instance):
        """Redirects all 404 errors to index.html to support SPA routing (SvelteKit)."""
        # If the request is for an API endpoint, return a standard 404 JSON
        if request_object.url.path.startswith(
            "/api"
        ) or request_object.url.path.startswith("/system"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})

        # Otherwise, serve the SPA index to let the frontend handle routing
        return FileResponse(os.path.join(static_assets_path, "index.html"))


@app.get("/health", operation_id="check_health")
def check_health():
    """Simple health check endpoint for monitoring."""
    return {"status": "healthy", "service": "tapehoard-backend"}
