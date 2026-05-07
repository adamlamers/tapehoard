import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from typing import Optional
from datetime import datetime
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session
from app.db.database import get_db, SessionLocal
from app.api.common import ScanStatusSchema, _active_job_exists
from app.db import models
from app.services.scanner import JobManager, scanner_manager

router = APIRouter(tags=["System"])


@router.post("/scan", operation_id="trigger_scan")
def trigger_scan(
    background_tasks: BackgroundTasks, db_session: Session = Depends(get_db)
):
    """Initiates a full metadata discovery scan of configured source roots."""
    if _active_job_exists(db_session, "SCAN"):
        raise HTTPException(status_code=400, detail="A scan job is already running")
    job_record = JobManager.create_job(db_session, "SCAN")

    def run_discovery_task():
        with SessionLocal() as db_inner:
            scanner_manager.scan_sources(db_inner, job_record.id)

    background_tasks.add_task(run_discovery_task)
    return {"message": "Scan started", "job_id": job_record.id}


@router.post("/index/hash", operation_id="trigger_indexing")
def trigger_indexing(
    background_tasks: BackgroundTasks, db_session: Session = Depends(get_db)
):
    """Manually triggers a background hashing marathon for unindexed files."""
    if scanner_manager.is_hashing:
        raise HTTPException(status_code=400, detail="Hashing job already in progress")

    background_tasks.add_task(scanner_manager.run_hashing)
    return {"message": "Background hashing task initiated"}


@router.get(
    "/scan/status", response_model=ScanStatusSchema, operation_id="get_scan_status"
)
def get_scan_status():
    """Returns the real-time operational status of the scanner and hashing engines."""
    return ScanStatusSchema(
        is_running=scanner_manager.is_running,
        files_processed=scanner_manager.files_processed,
        files_hashed=scanner_manager.files_hashed,
        files_new=scanner_manager.files_new,
        files_modified=scanner_manager.files_modified,
        files_missing=scanner_manager.files_missing,
        total_files_found=scanner_manager.total_files_found,
        current_path=scanner_manager.current_path,
        is_throttled=scanner_manager.is_throttled,
        hashing_speed=scanner_manager._format_throughput(),
        last_run_time=scanner_manager.last_run_time,
    )


@router.get("/scan/stream", operation_id="stream_scan_status")
async def stream_scan_status():
    """Server-Sent Events endpoint for real-time scan progress updates."""

    async def event_generator():
        while True:
            payload = {
                "is_running": scanner_manager.is_running,
                "files_processed": scanner_manager.files_processed,
                "files_hashed": scanner_manager.files_hashed,
                "files_new": scanner_manager.files_new,
                "files_modified": scanner_manager.files_modified,
                "files_missing": scanner_manager.files_missing,
                "total_files_found": scanner_manager.total_files_found,
                "current_path": scanner_manager.current_path,
                "is_throttled": scanner_manager.is_throttled,
                "hashing_speed": scanner_manager._format_throughput(),
                "last_run_time": (
                    scanner_manager.last_run_time.isoformat()
                    if scanner_manager.last_run_time
                    else None
                ),
            }
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _get_last_scan_time(db_session: Session) -> Optional[datetime]:
    """Returns the completion time of the most recent successful SCAN job."""
    last_scan = (
        db_session.query(models.Job)
        .filter(models.Job.job_type == "SCAN", models.Job.status == "COMPLETED")
        .order_by(models.Job.completed_at.desc())
        .first()
    )
    return last_scan.completed_at if last_scan else None
