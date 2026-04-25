import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from app.api import system, inventory, backups, restores
from app.db.database import engine
from app.db import models
from app.services.scheduler import scheduler_manager

# Create standard tables
models.Base.metadata.create_all(bind=engine)


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
    allow_origins=["*"],  # In production, this should be restricted
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
# We expect the 'build' directory to exist at the root level of the app
static_path = "static"
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
