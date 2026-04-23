from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import system, inventory, backups, restores
from app.db.database import engine
from app.db import models

# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="TapeHoard API",
    description="A robust, index-driven Tape Backup Manager",
    version="0.1.0",
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


@app.get("/")
def read_root():
    return {"message": "Welcome to TapeHoard API"}
