import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from app.api import system, inventory, backups, restores
from app.services.scheduler import scheduler_manager

# Note: Tables are created via Alembic migrations, not metadata.create_all
# to ensure FTS5 virtual tables and triggers are properly initialized.


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    scheduler_manager.start()
    yield
    # Shutdown
    scheduler_manager.stop()


app = FastAPI(
    title="TapeHoard API",
    description="A robust, index-driven Tape Backup Manager",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:8000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(system.router)
app.include_router(inventory.router)
app.include_router(backups.router)
app.include_router(restores.router)

# Mount frontend static files
# In Docker, static is in /app/backend/static
# In Dev, it might be in ./static (if run from backend/)
base_dir = os.path.dirname(os.path.abspath(__file__))
static_path = os.path.join(os.path.dirname(base_dir), "static")

if os.path.exists(static_path):
    app.mount("/", StaticFiles(directory=static_path, html=True), name="static")

    # Add catch-all route for SPA (SvelteKit)
    @app.exception_handler(404)
    async def spa_catch_all(request, exc):
        # If the request is for an API endpoint, return 404 normally
        if request.url.path.startswith(
            ("/system", "/inventory", "/backups", "/restores")
        ):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        # Otherwise, serve the SPA index
        return FileResponse(os.path.join(static_path, "index.html"))


@app.get("/health")
def health_check():
    return {"status": "healthy"}
