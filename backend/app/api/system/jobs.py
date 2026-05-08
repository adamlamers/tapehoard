from datetime import datetime
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.common import JobLogSchema, JobSchema
from app.db import models
from app.db.database import SessionLocal, get_db
from app.services.scanner import JobManager, scanner_manager
import json
import asyncio

router = APIRouter(tags=["System"])


def _get_latest_logs(db_session: Session, job_ids: list[int]) -> dict[int, str]:
    """Returns a mapping of job_id -> most recent log message for the given job IDs."""
    if not job_ids:
        return {}
    placeholders = ", ".join([f":id{i}" for i in range(len(job_ids))])
    params = {f"id{i}": jid for i, jid in enumerate(job_ids)}
    subquery = text(f"""
        SELECT jl.job_id, jl.message
        FROM job_logs jl
        INNER JOIN (
            SELECT job_id, MAX(id) as max_id
            FROM job_logs
            WHERE job_id IN ({placeholders})
            GROUP BY job_id
        ) latest ON jl.id = latest.max_id
    """)
    return {row[0]: row[1] for row in db_session.execute(subquery, params).fetchall()}


@router.get("/jobs", response_model=List[JobSchema], operation_id="list_jobs")
def list_jobs(limit: int = 10, offset: int = 0, db_session: Session = Depends(get_db)):
    """Returns a paginated list of background archival and discovery jobs."""
    jobs = (
        db_session.query(models.Job)
        .order_by(models.Job.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    latest_logs = _get_latest_logs(db_session, [job.id for job in jobs])

    result = []
    for job in jobs:
        job_dict = {
            "id": job.id,
            "job_type": job.job_type,
            "status": job.status,
            "progress": job.progress,
            "current_task": job.current_task,
            "error_message": job.error_message,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "created_at": job.created_at,
            "latest_log": latest_logs.get(job.id),
        }
        result.append(JobSchema(**job_dict))
    return result


@router.get("/jobs/count", operation_id="get_job_count")
def get_job_count(db_session: Session = Depends(get_db)):
    """Returns the total number of jobs recorded in the system."""
    return {"count": db_session.query(models.Job).count()}


@router.get("/jobs/stats", operation_id="get_job_stats")
def get_job_stats(db_session: Session = Depends(get_db)):
    """Returns summary statistics for all jobs."""
    total = db_session.query(models.Job).count()
    completed = (
        db_session.query(models.Job).filter(models.Job.status == "COMPLETED").count()
    )
    failed = db_session.query(models.Job).filter(models.Job.status == "FAILED").count()
    running = (
        db_session.query(models.Job).filter(models.Job.status == "RUNNING").count()
    )
    pending = (
        db_session.query(models.Job).filter(models.Job.status == "PENDING").count()
    )

    success_rate = (
        (completed / (completed + failed) * 100) if (completed + failed) > 0 else 100.0
    )

    avg_duration_result = db_session.execute(
        text("""
            SELECT AVG(
                CAST((julianday(completed_at) - julianday(started_at)) * 86400 AS INTEGER)
            ) as avg_seconds
            FROM jobs
            WHERE status = 'COMPLETED' AND started_at IS NOT NULL AND completed_at IS NOT NULL
        """)
    ).fetchone()
    avg_duration = (
        avg_duration_result[0] if avg_duration_result and avg_duration_result[0] else 0
    )

    job_type_counts = {}
    for row in db_session.execute(
        text("SELECT job_type, COUNT(*) as cnt FROM jobs GROUP BY job_type")
    ).fetchall():
        job_type_counts[row[0]] = row[1]

    return {
        "total": total,
        "completed": completed,
        "failed": failed,
        "running": running,
        "pending": pending,
        "success_rate": round(success_rate, 1),
        "avg_duration_seconds": round(avg_duration, 0),
        "job_type_counts": job_type_counts,
    }


# NOTE: /jobs/stream MUST be registered BEFORE /jobs/{job_id} routes
# because FastAPI matches routes in definition order.
@router.get("/jobs/stream", operation_id="stream_jobs")
async def stream_jobs(request: Request):
    """Server-Sent Events (SSE) endpoint for real-time job status updates."""

    async def event_generator():
        while not await request.is_disconnected():
            with SessionLocal() as db_session:
                active_jobs = (
                    db_session.query(models.Job)
                    .filter(models.Job.status.in_(["RUNNING", "PENDING"]))
                    .all()
                )
                latest_logs = _get_latest_logs(
                    db_session, [job.id for job in active_jobs]
                )

                serialized_data = []
                for job in active_jobs:
                    job_dict = {
                        "id": job.id,
                        "job_type": job.job_type,
                        "status": job.status,
                        "progress": job.progress,
                        "current_task": job.current_task,
                        "error_message": job.error_message,
                        "started_at": job.started_at,
                        "created_at": job.created_at,
                        "latest_log": latest_logs.get(job.id),
                    }
                    for date_field in ["started_at", "created_at"]:
                        val = job_dict[date_field]
                        if isinstance(val, datetime):
                            job_dict[date_field] = val.isoformat()
                    serialized_data.append(job_dict)

                yield f"data: {json.dumps(serialized_data)}\n\n"

            await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# NOTE: /jobs/{job_id}/logs/stream MUST be registered BEFORE /jobs/{job_id}/logs
# because FastAPI matches routes in definition order.
@router.get("/jobs/{job_id}/logs/stream", operation_id="stream_job_logs")
async def stream_job_logs(job_id: int, request: Request):
    """Server-Sent Events (SSE) endpoint for real-time job log streaming."""
    last_log_id = 0

    async def event_generator():
        nonlocal last_log_id
        while not await request.is_disconnected():
            with SessionLocal() as db_session:
                # Check if job exists
                job = db_session.get(models.Job, job_id)
                if not job:
                    yield f"data: {json.dumps({'error': 'Job not found'})}\n\n"
                    return

                # Get new logs since last check
                logs = (
                    db_session.query(models.JobLog)
                    .filter(models.JobLog.job_id == job_id)
                    .filter(models.JobLog.id > last_log_id)
                    .order_by(models.JobLog.id.asc())
                    .all()
                )

                if logs:
                    last_log_id = logs[-1].id
                    serialized_logs = [
                        {
                            "id": log.id,
                            "message": log.message,
                            "timestamp": log.timestamp.isoformat()
                            if isinstance(log.timestamp, datetime)
                            else log.timestamp,
                        }
                        for log in logs
                    ]
                    yield f"data: {json.dumps(serialized_logs)}\n\n"

                # Stop streaming if job is finished
                if job.status not in ["RUNNING", "PENDING"]:
                    yield f"data: {json.dumps({'complete': True})}\n\n"
                    return

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/jobs/{job_id}", response_model=JobSchema, operation_id="get_job")
def get_job(job_id: int, db_session: Session = Depends(get_db)):
    """Retrieves detailed metadata for a specific job."""
    job_record = db_session.get(models.Job, job_id)
    if not job_record:
        raise HTTPException(status_code=404, detail="Job not found")

    latest_log = (
        db_session.query(models.JobLog)
        .filter(models.JobLog.job_id == job_id)
        .order_by(models.JobLog.id.desc())
        .first()
    )

    return JobSchema(
        id=job_record.id,
        job_type=job_record.job_type,
        status=job_record.status,
        progress=job_record.progress,
        current_task=job_record.current_task,
        error_message=job_record.error_message,
        started_at=job_record.started_at,
        completed_at=job_record.completed_at,
        created_at=job_record.created_at,
        latest_log=latest_log.message if latest_log else None,
    )


@router.get(
    "/jobs/{job_id}/logs",
    response_model=List[JobLogSchema],
    operation_id="get_job_logs",
)
def get_job_logs(job_id: int, db_session: Session = Depends(get_db)):
    """Retrieves the full execution log for a specific job."""
    job_record = db_session.get(models.Job, job_id)
    if not job_record:
        raise HTTPException(status_code=404, detail="Job not found")

    logs = (
        db_session.query(models.JobLog)
        .filter(models.JobLog.job_id == job_id)
        .order_by(models.JobLog.id.asc())
        .all()
    )
    return [
        JobLogSchema(id=log.id, message=log.message, timestamp=log.timestamp)
        for log in logs
    ]


@router.post("/jobs/{job_id}/cancel", operation_id="cancel_job")
def cancel_job(job_id: int):
    """Submits a cancellation request for an active job."""
    JobManager.cancel_job(job_id)
    return {"message": "Cancellation request submitted"}


@router.post("/jobs/{job_id}/retry", operation_id="retry_job")
def retry_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(get_db),
):
    """Retries a failed SCAN job by creating a new job of the same type."""
    job_record = db_session.get(models.Job, job_id)
    if not job_record:
        raise HTTPException(status_code=404, detail="Job not found")
    if job_record.status != "FAILED":
        raise HTTPException(status_code=400, detail="Only failed jobs can be retried")

    new_job = JobManager.create_job(db_session, job_record.job_type)

    if job_record.job_type == "SCAN":

        def run_discovery_task():
            with SessionLocal() as db_inner:
                scanner_manager.scan_sources(db_inner, new_job.id)

        background_tasks.add_task(run_discovery_task)
    else:
        db_session.delete(new_job)
        db_session.commit()
        raise HTTPException(
            status_code=400,
            detail=f"Retry for {job_record.job_type} jobs is not supported. "
            f"Please re-trigger from the appropriate endpoint.",
        )

    return {
        "message": f"Retry initiated for {job_record.job_type} job",
        "new_job_id": new_job.id,
    }
