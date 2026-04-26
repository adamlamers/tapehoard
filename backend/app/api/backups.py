from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import models
from app.db.database import SessionLocal, get_db
from app.services.archiver import archiver_manager
from app.services.scanner import JobManager

router = APIRouter(prefix="/backups", tags=["Backups"])


# --- Request/Response Schemas ---


class BackupJobSchema(BaseModel):
    id: int
    job_name: str
    backup_type: str
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# --- Endpoints ---


@router.post("/trigger/{media_id}")
def trigger_backup_job(
    media_id: int,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(get_db),
):
    """Initiates a background archival job for a specific storage medium."""
    media_record = db_session.get(models.StorageMedia, media_id)
    if not media_record:
        raise HTTPException(status_code=404, detail="Storage media not found.")

    if media_record.status != "active":
        raise HTTPException(
            status_code=400,
            detail=f"Media is currently in '{media_record.status}' state and cannot accept new backups.",
        )

    # Create a unified Job record for tracking
    job_record = JobManager.create_job(db_session, "BACKUP")

    def run_archival_task():
        """Isolated worker task to perform the archival."""
        with SessionLocal() as db_inner:
            archiver_manager.run_backup(db_inner, media_id, job_record.id)

    background_tasks.add_task(run_archival_task)

    return {
        "message": "Archival job submitted to background worker.",
        "job_id": job_record.id,
        "media": media_record.identifier,
    }


@router.get("/", response_model=List[BackupJobSchema])
def list_archival_history(db_session: Session = Depends(get_db)):
    """Retrieves a history of archival jobs, sorted by most recent."""
    # Note: Using the generic Job model for consistency across the UI
    return (
        db_session.query(models.Job)
        .filter(models.Job.job_type == "BACKUP")
        .order_by(models.Job.created_at.desc())
        .all()
    )
