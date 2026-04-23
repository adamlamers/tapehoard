from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from app.db.database import get_db, SessionLocal
from app.db import models
from app.services.archiver import archiver_manager
from app.services.scanner import JobManager

router = APIRouter(prefix="/backups", tags=["Backups"])


@router.post("/trigger/{media_id}")
def trigger_backup(
    media_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
):
    media = db.query(models.StorageMedia).get(media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    if media.status != "active":
        raise HTTPException(status_code=400, detail="Media is not active")

    # Create the job record
    job = JobManager.create_job(db, "BACKUP")

    def run_backup_task():
        db_inner = SessionLocal()
        try:
            archiver_manager.run_backup(db_inner, media_id=media_id, job_id=job.id)
        finally:
            db_inner.close()

    background_tasks.add_task(run_backup_task)
    return {"message": "Backup job initiated", "job_id": job.id}


@router.get("/")
def list_backups():
    return []
