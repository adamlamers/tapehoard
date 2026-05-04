import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pathspec
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.api.schemas import BatchDiscrepancyAction, DiscrepancySchema, TreeNodeSchema
from app.db import models
from app.db.database import SessionLocal, get_db
from app.services.scanner import JobManager, scanner_manager

router = APIRouter(prefix="/system", tags=["System"])


def _active_job_exists(db_session: Session, job_type: str) -> bool:
    """Return True if an active (non-completed/failed/cancelled) job of the given type exists. (MEDIUM #16)"""
    return (
        db_session.query(models.Job)
        .filter(
            models.Job.job_type == job_type,
            models.Job.status.in_(["PENDING", "RUNNING"]),
            models.Job.is_cancelled.is_(False),
        )
        .first()
        is not None
    )


# --- Request/Response Schemas ---


class DashboardStatsSchema(BaseModel):
    monitored_files_count: int
    hashed_files_count: int
    total_data_size: int
    archived_data_size: int
    ignored_files_count: int
    ignored_data_size: int
    unprotected_files_count: int
    unprotected_data_size: int
    discrepancies_count: int
    media_distribution: Dict[str, int]
    last_scan_time: Optional[datetime]
    redundancy_ratio: float


class JobSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_type: str
    status: str
    progress: float
    current_task: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    latest_log: Optional[str] = None


class JobLogSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    message: str
    timestamp: datetime


class FileItemSchema(BaseModel):
    name: str
    path: str
    type: str
    size: Optional[int] = None
    mtime: Optional[float] = None
    ignored: bool = False
    sha256_hash: Optional[str] = None


class BrowseResponseSchema(BaseModel):
    files: List[FileItemSchema]
    last_scan_time: Optional[datetime] = None


class TrackToggleRequest(BaseModel):
    path: str
    is_directory: bool = True


class BatchTrackRequest(BaseModel):
    tracks: List[str] = []
    untracks: List[str] = []


class ScanStatusSchema(BaseModel):
    is_running: bool
    files_processed: int
    files_hashed: int
    files_new: int
    files_modified: int
    files_missing: int
    total_files_found: int
    current_path: str
    is_throttled: bool
    hashing_speed: str
    last_run_time: Optional[datetime] = None


class SettingSchema(BaseModel):
    key: str
    value: str


class TestNotificationRequest(BaseModel):
    url: str


class IgnoreHardwareRequest(BaseModel):
    identifier: str


# --- Helpers ---


def get_source_roots(db_session: Session) -> List[str]:
    """Retrieves the list of configured source root paths."""
    settings_record = (
        db_session.query(models.SystemSetting)
        .filter(models.SystemSetting.key == "source_roots")
        .first()
    )
    if settings_record:
        try:
            return json.loads(settings_record.value)
        except Exception:
            return [settings_record.value]

    return ["/source_data"]


def get_exclusion_spec(db_session: Session) -> Optional[pathspec.PathSpec]:
    """Compiles a gitignore-style exclusion matcher from system settings."""
    settings_record = (
        db_session.query(models.SystemSetting)
        .filter(models.SystemSetting.key == "global_exclusions")
        .first()
    )
    if not settings_record or not settings_record.value.strip():
        return None

    exclusion_patterns = [
        pattern.strip()
        for pattern in settings_record.value.splitlines()
        if pattern.strip()
    ]
    return pathspec.PathSpec.from_lines("gitwildmatch", exclusion_patterns)


def get_ignored_status(
    absolute_path: str,
    tracking_map: Dict[str, str],
    exclusion_spec: Optional[pathspec.PathSpec],
) -> bool:
    """Determines if a path should be ignored based on user policy (overrides) and global exclusions."""
    # 1. Check user-defined tracking policy (Explicit overrides)
    applicable_rules = []
    for rule_path, action in tracking_map.items():
        if absolute_path == rule_path or absolute_path.startswith(rule_path + "/"):
            applicable_rules.append((len(rule_path), action))

    if applicable_rules:
        # Most specific rule wins
        applicable_rules.sort(key=lambda x: x[0], reverse=True)
        return applicable_rules[0][1] == "exclude"

    # 2. Check global exclusions (Default automatic behavior)
    if exclusion_spec and exclusion_spec.match_file(absolute_path):
        return True

    return False


def _validate_path_within_roots(path: str, roots: List[str]) -> bool:
    """Validates that a path does not contain traversal sequences and is within configured roots."""
    if ".." in path:
        return False
    abs_path = os.path.abspath(path)
    for root in roots:
        abs_root = os.path.abspath(root)
        if abs_path == abs_root or abs_path.startswith(abs_root + os.sep):
            return True
    return False


# --- Endpoints ---


@router.post("/test/reset")
def reset_test_environment(db_session: Session = Depends(get_db)):
    """Wipes the database and resets state for E2E testing."""
    import os

    if os.environ.get("TAPEHOARD_TEST_MODE") != "true":
        raise HTTPException(status_code=403, detail="Reset only allowed in test mode")

    # Wipe tables
    db_session.query(models.FileVersion).delete()
    db_session.query(models.RestoreCart).delete()
    db_session.query(models.Job).delete()
    db_session.query(models.TrackedSource).delete()
    db_session.query(models.FilesystemState).delete()
    db_session.query(models.StorageMedia).delete()
    # Note: Keep SystemSettings if needed, or wipe them too
    db_session.query(models.SystemSetting).delete()

    db_session.commit()

    # Clear mock hardware dirs if we can find them
    # But usually the test will re-initialize them

    return {"message": "Test environment reset"}


@router.get("/dashboard/stats", response_model=DashboardStatsSchema)
def get_dashboard_stats(db_session: Session = Depends(get_db)):
    """Computes high-level system statistics for the overview dashboard."""
    aggregation_sql = text("""
        SELECT
            COUNT(*) as total_count,
            SUM(size) as total_size,
            SUM(CASE WHEN is_ignored = 1 THEN 1 ELSE 0 END) as ignored_count,
            SUM(CASE WHEN is_ignored = 1 THEN size ELSE 0 END) as ignored_size,
            SUM(CASE WHEN is_ignored = 0 AND is_deleted = 0 AND id NOT IN (
                SELECT fv.filesystem_state_id FROM file_versions fv
                JOIN storage_media sm ON sm.id = fv.media_id
                WHERE sm.status IN ('active', 'full')
            ) THEN 1 ELSE 0 END) as unprotected_count,
            SUM(CASE WHEN is_ignored = 0 AND is_deleted = 0 AND id NOT IN (
                SELECT fv.filesystem_state_id FROM file_versions fv
                JOIN storage_media sm ON sm.id = fv.media_id
                WHERE sm.status IN ('active', 'full')
            ) THEN size ELSE 0 END) as unprotected_size,
            SUM(CASE WHEN sha256_hash IS NOT NULL AND is_ignored = 0 AND is_deleted = 0 THEN 1 ELSE 0 END) as hashed_count,
            SUM(CASE WHEN is_ignored = 0 AND is_deleted = 0 THEN 1 ELSE 0 END) as eligible_count,
            SUM(CASE WHEN is_deleted = 0 AND id IN (
                SELECT fv.filesystem_state_id FROM file_versions fv
                JOIN storage_media sm ON sm.id = fv.media_id
                WHERE sm.status IN ('active', 'full')
            ) THEN size ELSE 0 END) as archived_size,
            SUM(CASE WHEN is_deleted = 1 THEN 1 ELSE 0 END) as missing_count,
            SUM(CASE WHEN is_deleted = 1 AND missing_acknowledged_at IS NULL AND is_ignored = 0 THEN 1 ELSE 0 END) as active_discrepancies_count
        FROM filesystem_state
    """)

    res = db_session.execute(aggregation_sql).fetchone()
    if res:
        total_count, total_size = res[0] or 0, res[1] or 0
        ignored_count, ignored_size = res[2] or 0, res[3] or 0
        unprotected_count, unprotected_size = res[4] or 0, res[5] or 0
        hashed_count = res[6] or 0
        eligible_count = res[7] or 0
        archived_size = res[8] or 0
        # missing_count = res[9] or 0
        active_discrepancies_count = res[10] or 0
    else:
        total_count = total_size = ignored_count = ignored_size = unprotected_count = (
            unprotected_size
        ) = hashed_count = eligible_count = archived_size = (
            active_discrepancies_count
        ) = 0

    media_counts = {
        "LTO": db_session.query(models.StorageMedia)
        .filter(models.StorageMedia.media_type == "tape")
        .count(),
        "HDD": db_session.query(models.StorageMedia)
        .filter(models.StorageMedia.media_type == "hdd")
        .count(),
        "Cloud": db_session.query(models.StorageMedia)
        .filter(models.StorageMedia.media_type == "cloud")
        .count(),
    }

    last_scan = (
        db_session.query(models.Job)
        .filter(models.Job.job_type == "SCAN", models.Job.status == "COMPLETED")
        .order_by(models.Job.completed_at.desc())
        .first()
    )

    total_versions = (
        db_session.query(func.count(models.FileVersion.id))
        .join(
            models.StorageMedia, models.StorageMedia.id == models.FileVersion.media_id
        )
        .filter(models.StorageMedia.status.in_(["active", "full"]))
        .scalar()
        or 0
    )
    eligible_redundancy_count = max(total_count - ignored_count, 1)
    redundancy_percentage = (total_versions / eligible_redundancy_count) * 100

    return DashboardStatsSchema(
        monitored_files_count=eligible_count,
        hashed_files_count=hashed_count,
        total_data_size=total_size,
        archived_data_size=archived_size,
        ignored_files_count=ignored_count,
        ignored_data_size=ignored_size,
        unprotected_files_count=unprotected_count,
        unprotected_data_size=unprotected_size,
        discrepancies_count=active_discrepancies_count,
        media_distribution=media_counts,
        last_scan_time=last_scan.completed_at if last_scan else None,
        redundancy_ratio=round(redundancy_percentage, 1),
    )


@router.get("/jobs", response_model=List[JobSchema])
def list_jobs(limit: int = 10, offset: int = 0, db_session: Session = Depends(get_db)):
    """Returns a paginated list of background archival and discovery jobs."""
    jobs = (
        db_session.query(models.Job)
        .order_by(models.Job.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )

    job_ids = [job.id for job in jobs]
    if job_ids:
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
        latest_logs = {
            row[0]: row[1] for row in db_session.execute(subquery, params).fetchall()
        }
    else:
        latest_logs = {}

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


@router.get("/jobs/count")
def get_jobs_count(db_session: Session = Depends(get_db)):
    """Returns the total number of jobs recorded in the system."""
    return {"count": db_session.query(models.Job).count()}


@router.get("/jobs/stats")
def get_jobs_stats(db_session: Session = Depends(get_db)):
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


@router.get("/jobs/{job_id}", response_model=JobSchema)
def get_job_detail(job_id: int, db_session: Session = Depends(get_db)):
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


@router.get("/jobs/{job_id}/logs", response_model=List[JobLogSchema])
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


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    """Submits a cancellation request for an active job."""
    JobManager.cancel_job(job_id)
    return {"message": "Cancellation request submitted"}


@router.post("/jobs/{job_id}/retry")
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


@router.get("/jobs/stream")
async def stream_jobs():
    """Server-Sent Events (SSE) endpoint for real-time job status updates."""

    async def event_generator():
        while True:
            with SessionLocal() as db_session:
                active_jobs = (
                    db_session.query(models.Job)
                    .filter(models.Job.status.in_(["RUNNING", "PENDING"]))
                    .all()
                )
                job_ids = [job.id for job in active_jobs]
                if job_ids:
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
                    latest_logs = {
                        row[0]: row[1]
                        for row in db_session.execute(subquery, params).fetchall()
                    }
                else:
                    latest_logs = {}

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
                        from datetime import datetime

                        val = job_dict[date_field]
                        if isinstance(val, datetime):
                            job_dict[date_field] = val.isoformat()
                    serialized_data.append(job_dict)

                yield f"data: {json.dumps(serialized_data)}\n\n"
            import asyncio

            await asyncio.sleep(2)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/scan")
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


@router.post("/index/hash")
def trigger_indexing(
    background_tasks: BackgroundTasks, db_session: Session = Depends(get_db)
):
    """Manually triggers a background hashing marathon for unindexed files."""
    if scanner_manager.is_hashing:
        raise HTTPException(status_code=400, detail="Hashing job already in progress")

    background_tasks.add_task(scanner_manager.run_hashing)
    return {"message": "Background hashing task initiated"}


@router.get("/scan/status", response_model=ScanStatusSchema)
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


def _get_last_scan_time(db_session: Session) -> Optional[datetime]:
    """Returns the completion time of the most recent successful SCAN job."""
    last_scan = (
        db_session.query(models.Job)
        .filter(models.Job.job_type == "SCAN", models.Job.status == "COMPLETED")
        .order_by(models.Job.completed_at.desc())
        .first()
    )
    return last_scan.completed_at if last_scan else None


@router.get("/browse", response_model=BrowseResponseSchema)
def browse_system_path(
    path: Optional[str] = None, db_session: Session = Depends(get_db)
):
    """Provides a browsable view of the indexed filesystem from the database."""
    roots = get_source_roots(db_session)
    tracking_rules = db_session.query(models.TrackedSource).all()
    tracking_map = {rule.path: rule.action for rule in tracking_rules}
    exclusion_spec = get_exclusion_spec(db_session)
    last_scan_time = _get_last_scan_time(db_session)

    if path is None or path == "ROOT":
        results = []
        for root_path in roots:
            is_ignored = get_ignored_status(root_path, tracking_map, exclusion_spec)
            results.append(
                FileItemSchema(
                    name=root_path,
                    path=root_path,
                    type="directory",
                    ignored=is_ignored,
                )
            )
        return BrowseResponseSchema(files=results, last_scan_time=last_scan_time)

    if not _validate_path_within_roots(path, roots):
        raise HTTPException(
            status_code=403, detail="Path is outside configured source roots"
        )

    target_prefix = path if path.endswith("/") else path + "/"

    # Escape LIKE wildcards in the prefix
    escaped_prefix = (
        target_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )

    files_sql = text("""
        SELECT file_path, size, mtime, sha256_hash, is_ignored
        FROM filesystem_state
        WHERE file_path LIKE :prefix ESCAPE '\\'
        AND file_path != :prefix
    """)
    rows = db_session.execute(files_sql, {"prefix": f"{escaped_prefix}%"}).fetchall()

    if not rows and os.path.isdir(path):
        try:
            live_results = []
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        if entry.name.startswith("."):
                            continue
                        entry_path = entry.path
                        is_dir = entry.is_dir()
                        is_ignored = get_ignored_status(
                            entry_path, tracking_map, exclusion_spec
                        )
                        if is_dir:
                            live_results.append(
                                FileItemSchema(
                                    name=entry.name,
                                    path=entry_path,
                                    type="directory",
                                    ignored=is_ignored,
                                )
                            )
                        else:
                            stat = entry.stat()
                            live_results.append(
                                FileItemSchema(
                                    name=entry.name,
                                    path=entry_path,
                                    type="file",
                                    size=stat.st_size,
                                    mtime=stat.st_mtime,
                                    ignored=is_ignored,
                                    sha256_hash=None,
                                )
                            )
                    except OSError:
                        continue
            live_results.sort(key=lambda x: (x.type != "directory", x.name.lower()))
            return BrowseResponseSchema(
                files=live_results, last_scan_time=last_scan_time
            )
        except OSError:
            pass

    results = []
    seen = set()

    for file_path, size, mtime, sha256_hash, is_ignored in rows:
        relative = file_path[len(target_prefix) :]
        if "/" in relative:
            immediate_name = relative.split("/")[0]
            child_path = target_prefix + immediate_name
            if child_path not in seen:
                seen.add(child_path)
                dir_ignored = get_ignored_status(
                    child_path, tracking_map, exclusion_spec
                )
                results.append(
                    FileItemSchema(
                        name=immediate_name,
                        path=child_path,
                        type="directory",
                        ignored=dir_ignored,
                    )
                )
        else:
            if file_path not in seen:
                seen.add(file_path)
                results.append(
                    FileItemSchema(
                        name=relative,
                        path=file_path,
                        type="file",
                        size=size,
                        mtime=mtime,
                        ignored=is_ignored,
                        sha256_hash=sha256_hash,
                    )
                )

    results.sort(key=lambda x: (x.type != "directory", x.name.lower()))
    return BrowseResponseSchema(files=results, last_scan_time=last_scan_time)


@router.get("/search", response_model=List[FileItemSchema])
def search_system_index(
    q: str,
    path: Optional[str] = None,
    include_ignored: bool = False,
    db_session: Session = Depends(get_db),
):
    """Instantaneous full-text search across the entire indexed filesystem, optionally scoped by path."""
    if not q or len(q) < 3:
        return []

    ignore_filter = " AND fs.is_ignored = 0" if not include_ignored else ""
    path_filter = ""
    query_params = {"query": f'"{q}"'}

    if path and path != "ROOT":
        path_filter = " AND fs.file_path LIKE :path_prefix"
        query_params["path_prefix"] = f"{path}%"

    search_sql = text(
        f"""
        SELECT fs.file_path, fs.size, fs.mtime, fs.id, fs.is_ignored, fs.sha256_hash
        FROM filesystem_fts
        JOIN filesystem_state fs ON fs.id = filesystem_fts.rowid
        WHERE filesystem_fts MATCH :query {ignore_filter} {path_filter}
        AND fs.sha256_hash IS NOT NULL
        LIMIT 200
    """
    )

    files = db_session.execute(search_sql, query_params).fetchall()

    results = []
    for file_record in files:
        full_path = file_record[0]
        # Trust the indexed ignore state from the DB
        db_ignored = bool(file_record[4])

        results.append(
            FileItemSchema(
                name=full_path.split("/")[-1],
                path=full_path,
                type="file",
                size=file_record[1],
                mtime=file_record[2],
                ignored=db_ignored,
                sha256_hash=file_record[5],
            )
        )

    results.sort(key=lambda x: x.name.lower())
    return results


@router.post("/track/batch")
def batch_update_tracking(
    request_data: BatchTrackRequest, db_session: Session = Depends(get_db)
):
    """Applies bulk inclusion and exclusion rules and synchronizes is_ignored flags."""
    all_paths = list(request_data.tracks) + list(request_data.untracks)
    # Batch-fetch existing TrackedSource records (MEDIUM #15)
    existing_records = (
        db_session.query(models.TrackedSource)
        .filter(models.TrackedSource.path.in_(all_paths))
        .all()
        if all_paths
        else []
    )
    existing_map = {r.path: r for r in existing_records}

    # 1. Update Tracking Rules and set is_ignored = 0 for inclusions
    for path_to_track in request_data.tracks:
        if path_to_track in existing_map:
            existing_map[path_to_track].action = "include"
        else:
            db_session.add(models.TrackedSource(path=path_to_track, action="include"))

        # Mark files as NOT ignored (i.e., Tracked for Archival)
        db_session.execute(
            text(
                "UPDATE filesystem_state SET is_ignored = 0 WHERE file_path = :p OR file_path LIKE :pp"
            ),
            {"p": path_to_track, "pp": f"{path_to_track}/%"},
        )

    # 2. Update Tracking Rules and set is_ignored = 1 for exclusions
    for path_to_untrack in request_data.untracks:
        if path_to_untrack in existing_map:
            existing_map[path_to_untrack].action = "exclude"
        else:
            db_session.add(models.TrackedSource(path=path_to_untrack, action="exclude"))

        # Mark files as IGNORED (i.e., Untracked/Excluded from Archival)
        db_session.execute(
            text(
                "UPDATE filesystem_state SET is_ignored = 1 WHERE file_path = :p OR file_path LIKE :pp"
            ),
            {"p": path_to_untrack, "pp": f"{path_to_untrack}/%"},
        )

    db_session.commit()
    return {"message": "Tracking policy synchronized with filesystem index."}


@router.get("/settings", response_model=Dict[str, str])
def get_system_settings(db_session: Session = Depends(get_db)):
    """Retrieves all global system configuration key-value pairs."""
    settings_records = db_session.query(models.SystemSetting).all()
    return {record.key: record.value for record in settings_records}


@router.post("/settings")
def update_system_setting(
    setting_data: SettingSchema, db_session: Session = Depends(get_db)
):
    """Updates or creates a global system configuration setting."""
    existing_record = (
        db_session.query(models.SystemSetting)
        .filter(models.SystemSetting.key == setting_data.key)
        .first()
    )
    if existing_record:
        existing_record.value = setting_data.value
    else:
        db_session.add(
            models.SystemSetting(key=setting_data.key, value=setting_data.value)
        )
    db_session.commit()

    # Reload schedules in case scan/archival frequency changed
    if setting_data.key in ["schedule_scan", "schedule_archival"]:
        from app.services.scheduler import scheduler_manager

        scheduler_manager.reload()

    return {"message": "Setting committed."}


@router.post("/notifications/test")
def test_notification_dispatch(request_data: TestNotificationRequest):
    """Dispatches a test alert to the provided Apprise URL."""
    from app.services.notifications import notification_manager

    if notification_manager.test_notification(request_data.url):
        return {"message": "Notification dispatched successfully."}

    raise HTTPException(status_code=500, detail="Failed to dispatch test alert.")


@router.get("/ls")
def list_host_directories(path: str = "/"):
    """Lists subdirectories on the host system for UI path selection."""
    if ".." in path:
        raise HTTPException(status_code=403, detail="Path traversal not allowed")
    if not os.path.exists(path) or not os.path.isdir(path):
        return []

    try:
        results = []
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_dir() and not entry.name.startswith("."):
                        results.append({"name": entry.name, "path": entry.path})
                except OSError:
                    continue
        results.sort(key=lambda x: x["name"].lower())
        return results
    except Exception as directory_error:
        logger.error(f"Host LS failed for {path}: {directory_error}")
        raise HTTPException(status_code=500, detail=str(directory_error))


@router.get("/hardware/discover")
def discover_hardware_nodes(db_session: Session = Depends(get_db)):
    """Polls host hardware and mount points to discover unregistered storage media."""
    discovered_nodes = []

    # Load Ignore List
    ignored_record = (
        db_session.query(models.SystemSetting)
        .filter(models.SystemSetting.key == "ignored_hardware")
        .first()
    )
    ignore_list = json.loads(ignored_record.value) if ignored_record else []

    # 1. Probe Configured LTO Drives
    drive_record = (
        db_session.query(models.SystemSetting)
        .filter(models.SystemSetting.key == "tape_drives")
        .first()
    )
    if drive_record:
        try:
            device_paths = json.loads(drive_record.value)
            for dev_path in device_paths:
                from app.providers.tape import LTOProvider

                tape_provider = LTOProvider(config={"device_path": dev_path})
                state = tape_provider.get_live_info()

                if state["online"]:
                    barcode = state["identity"]
                    if barcode in ignore_list:
                        continue

                    # Check if this tape is already known by barcode OR serial number
                    is_known = False
                    if barcode:
                        is_known = (
                            db_session.query(models.StorageMedia)
                            .filter(models.StorageMedia.identifier == barcode)
                            .first()
                            is not None
                        )

                    mam_info = state["tape"]
                    if not is_known and mam_info.get("serial"):
                        is_known = (
                            db_session.query(models.StorageMedia)
                            .filter(
                                models.StorageMedia.identifier == mam_info["serial"]
                            )
                            .first()
                            is not None
                        )

                    discovered_nodes.append(
                        {
                            "type": "tape",
                            "device_path": dev_path,
                            "identifier": state["identity"] or "NEW TAPE",
                            "is_registered": is_known,
                            "status": "ready" if not is_known else "active",
                            "hardware_info": {
                                "drive": state["drive"],
                                "tape": state["tape"],
                            },
                        }
                    )
        except Exception as tape_error:
            logger.error(f"Tape discovery failed: {tape_error}")

    # 2. Probe Potential Mount Points
    potential_mounts = ["/mnt", "/media", "/Volumes", os.path.expanduser("~")]
    try:
        root_device_id = os.stat("/").st_dev
    except Exception:
        root_device_id = None

    restore_record = (
        db_session.query(models.SystemSetting)
        .filter(models.SystemSetting.key == "restore_destinations")
        .first()
    )
    restricted_paths = json.loads(restore_record.value) if restore_record else []

    for base_mount in potential_mounts:
        if not os.path.exists(base_mount):
            continue
        try:
            with os.scandir(base_mount) as it:
                for entry in it:
                    if not entry.is_dir():
                        continue

                    if entry.path in restricted_paths or entry.path in ignore_list:
                        continue

                    # Check for TapeHoard signature
                    id_file_path = os.path.join(entry.path, ".tapehoard_id")
                    disk_barcode = None
                    has_signature = os.path.exists(id_file_path)

                    if has_signature:
                        with open(id_file_path, "r") as f:
                            disk_barcode = f.read().strip()
                    else:
                        # Security & System Filtering (only for uninitialized disks to prevent scanning /)
                        try:
                            entry_stats = os.stat(entry.path)
                            if (
                                root_device_id is not None
                                and entry_stats.st_dev == root_device_id
                            ):
                                continue
                        except Exception:
                            continue

                    if disk_barcode in ignore_list:
                        continue
                    is_known = (
                        db_session.query(models.StorageMedia)
                        .filter(models.StorageMedia.identifier == disk_barcode)
                        .first()
                        is not None
                    )

                    if not is_known:
                        # Auto-detect capacity and UUID for HDDs
                        capacity_bytes = None
                        device_uuid = None
                        try:
                            from app.core.utils import get_path_uuid

                            device_uuid = get_path_uuid(entry.path)

                            st = os.statvfs(entry.path)
                            capacity_bytes = st.f_blocks * st.f_frsize
                        except Exception:
                            pass

                        discovered_nodes.append(
                            {
                                "type": "hdd",
                                "mount_path": entry.path,
                                "identifier": disk_barcode or "NEW DISK",
                                "is_registered": False,
                                "status": "uninitialized",
                                "capacity_bytes": capacity_bytes,
                                "device_uuid": device_uuid,
                            }
                        )
        except Exception:
            continue

    return discovered_nodes


@router.post("/hardware/ignore")
def ignore_hardware_node(
    request_data: IgnoreHardwareRequest, db_session: Session = Depends(get_db)
):
    """Appends a hardware identifier to the global ignore list."""
    setting_record = (
        db_session.query(models.SystemSetting)
        .filter(models.SystemSetting.key == "ignored_hardware")
        .first()
    )
    if not setting_record:
        setting_record = models.SystemSetting(key="ignored_hardware", value="[]")
        db_session.add(setting_record)

    ignored_items = json.loads(setting_record.value)
    if request_data.identifier not in ignored_items:
        ignored_items.append(request_data.identifier)
        setting_record.value = json.dumps(ignored_items)
        db_session.commit()

    return {"message": "Hardware node ignored."}


@router.get("/database/export")
def export_database_index():
    """Generates a clean backup of the active SQLite database."""
    database_url = os.getenv("DATABASE_URL", "sqlite:///tapehoard.db")
    database_path = database_url.replace("sqlite:///", "")

    if not os.path.exists(database_path):
        database_path = "tapehoard.db"
        if not os.path.exists(database_path):
            raise HTTPException(status_code=404, detail="Index not found.")

    export_temporary_path = "tapehoard_export.db"
    try:
        source_connection = sqlite3.connect(database_path)
        destination_connection = sqlite3.connect(export_temporary_path)
        with destination_connection:
            source_connection.backup(destination_connection)
        source_connection.close()
        destination_connection.close()

        return FileResponse(
            export_temporary_path,
            filename=f"tapehoard_index_{datetime.now(timezone.utc).strftime('%Y%m%d')}.db",
            background=BackgroundTasks().add_task(
                lambda: (
                    os.remove(export_temporary_path)
                    if os.path.exists(export_temporary_path)
                    else None
                )
            ),
        )
    except Exception as export_error:
        if os.path.exists(export_temporary_path):
            os.remove(export_temporary_path)
        raise HTTPException(
            status_code=500, detail=f"Export failed: {str(export_error)}"
        )


@router.post("/database/import")
async def import_database_index(file: Any, db_session: Session = Depends(get_db)):
    """Overwrites the current system state with an imported index file."""
    # Implementation pending - requires careful session termination
    return {"message": "Import logic restricted for safety."}


@router.get("/tree", response_model=List[TreeNodeSchema])
def get_system_tree(path: Optional[str] = None, db_session: Session = Depends(get_db)):
    """Returns a recursive tree view of the system for configuration."""
    from app.api.inventory import TreeNodeSchema

    roots = get_source_roots(db_session)
    if path is None or path == "ROOT":
        return [
            TreeNodeSchema(name=root, path=root, has_children=True) for root in roots
        ]

    if not _validate_path_within_roots(path, roots):
        raise HTTPException(
            status_code=403, detail="Path is outside configured source roots"
        )

    results = []
    if os.path.exists(path):
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if entry.is_dir() and not entry.name.startswith("."):
                        results.append(
                            TreeNodeSchema(
                                name=entry.name, path=entry.path, has_children=True
                            )
                        )
        except Exception:
            pass
    results.sort(key=lambda x: x.name.lower())
    return results


# --- Discrepancy Endpoints ---


@router.get("/discrepancies", response_model=List[DiscrepancySchema])
def list_discrepancies(db_session: Session = Depends(get_db)):
    """Lists files with discrepancies: confirmed deleted or unhashed and missing from disk."""
    deleted_records = (
        db_session.query(models.FilesystemState)
        .filter(
            models.FilesystemState.is_deleted.is_(True),
            models.FilesystemState.is_ignored.is_(False),
            models.FilesystemState.missing_acknowledged_at.is_(None),
        )
        .order_by(models.FilesystemState.last_seen_timestamp.desc())
        .all()
    )

    unhashed_missing = (
        db_session.query(models.FilesystemState)
        .filter(
            models.FilesystemState.sha256_hash.is_(None),
            models.FilesystemState.is_ignored.is_(False),
            models.FilesystemState.is_deleted.is_(False),
            models.FilesystemState.missing_acknowledged_at.is_(None),
        )
        .all()
    )

    # Batch-load valid version flags to avoid N+1 (MEDIUM #14)
    all_records = deleted_records + unhashed_missing
    record_ids = {r.id for r in all_records}
    if record_ids:
        valid_version_rows = (
            db_session.query(models.FileVersion.filesystem_state_id)
            .join(models.StorageMedia)
            .filter(
                models.FileVersion.filesystem_state_id.in_(record_ids),
                models.StorageMedia.status.in_(["active", "full"]),
            )
            .distinct()
            .all()
        )
        ids_with_valid_versions = {row[0] for row in valid_version_rows}
    else:
        ids_with_valid_versions = set()

    results = []
    seen_ids = set()
    for record in all_records:
        if record.id in seen_ids:
            continue
        seen_ids.add(record.id)

        has_valid_versions = record.id in ids_with_valid_versions

        if record.is_deleted:
            results.append(
                DiscrepancySchema(
                    id=record.id,
                    path=record.file_path,
                    size=record.size,
                    mtime=datetime.fromtimestamp(record.mtime, tz=timezone.utc),
                    last_seen_timestamp=record.last_seen_timestamp,
                    sha256_hash=record.sha256_hash,
                    is_deleted=True,
                    has_versions=has_valid_versions,
                )
            )
        elif not os.path.exists(record.file_path):
            results.append(
                DiscrepancySchema(
                    id=record.id,
                    path=record.file_path,
                    size=record.size,
                    mtime=datetime.fromtimestamp(record.mtime, tz=timezone.utc),
                    last_seen_timestamp=record.last_seen_timestamp,
                    sha256_hash=record.sha256_hash,
                    is_deleted=False,
                    has_versions=has_valid_versions,
                )
            )

    return results


def _resolve_ids_from_action(
    action: BatchDiscrepancyAction, db_session: Session
) -> List[int]:
    if action.ids:
        return action.ids
    if action.path_prefix:
        records = (
            db_session.query(models.FilesystemState)
            .filter(models.FilesystemState.file_path.startswith(action.path_prefix))
            .all()
        )
        return [r.id for r in records]
    return []


@router.post("/discrepancies/batch/confirm")
def batch_confirm_deleted(
    action: BatchDiscrepancyAction, db_session: Session = Depends(get_db)
):
    ids = _resolve_ids_from_action(action, db_session)
    if not ids:
        raise HTTPException(status_code=400, detail="No IDs or path prefix provided")
    db_session.query(models.FilesystemState).filter(
        models.FilesystemState.id.in_(ids)
    ).update({models.FilesystemState.is_deleted: True}, synchronize_session="fetch")
    db_session.commit()
    return {
        "message": f"{len(ids)} file(s) marked as confirmed deleted",
        "count": len(ids),
    }


@router.post("/discrepancies/batch/dismiss")
def batch_dismiss(
    action: BatchDiscrepancyAction, db_session: Session = Depends(get_db)
):
    ids = _resolve_ids_from_action(action, db_session)
    if not ids:
        raise HTTPException(status_code=400, detail="No IDs or path prefix provided")
    db_session.query(models.FilesystemState).filter(
        models.FilesystemState.id.in_(ids)
    ).update(
        {
            models.FilesystemState.missing_acknowledged_at: datetime.now(timezone.utc),
        },
        synchronize_session="fetch",
    )
    db_session.commit()
    return {"message": f"{len(ids)} discrepancy(ies) dismissed", "count": len(ids)}


@router.post("/discrepancies/batch/delete")
def batch_hard_delete(
    action: BatchDiscrepancyAction, db_session: Session = Depends(get_db)
):
    ids = _resolve_ids_from_action(action, db_session)
    if not ids:
        raise HTTPException(status_code=400, detail="No IDs or path prefix provided")
    db_session.query(models.RestoreCart).filter(
        models.RestoreCart.filesystem_state_id.in_(ids)
    ).delete(synchronize_session="fetch")
    db_session.query(models.FileVersion).filter(
        models.FileVersion.filesystem_state_id.in_(ids)
    ).delete(synchronize_session="fetch")
    db_session.query(models.FilesystemState).filter(
        models.FilesystemState.id.in_(ids)
    ).delete(synchronize_session="fetch")
    db_session.commit()
    return {"message": f"{len(ids)} record(s) permanently deleted", "count": len(ids)}


@router.post("/discrepancies/{file_id}/confirm")
def confirm_file_deleted(file_id: int, db_session: Session = Depends(get_db)):
    """Marks a file as confirmed deleted (soft delete)."""
    record = db_session.get(models.FilesystemState, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File record not found")
    record.is_deleted = True
    db_session.commit()
    return {"message": f"File '{record.file_path}' marked as deleted"}


@router.post("/discrepancies/{file_id}/dismiss")
def dismiss_discrepancy(file_id: int, db_session: Session = Depends(get_db)):
    """Acknowledges a missing file — hides it from discrepancies."""
    record = db_session.get(models.FilesystemState, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File record not found")
    record.missing_acknowledged_at = datetime.now(timezone.utc)
    db_session.commit()
    return {"message": f"File '{record.file_path}' discrepancy dismissed"}


@router.post("/discrepancies/{file_id}/undo-dismiss")
def undo_dismiss_discrepancy(file_id: int, db_session: Session = Depends(get_db)):
    """Clears the acknowledged state so the file reappears in discrepancies (MEDIUM #22)."""
    record = db_session.get(models.FilesystemState, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File record not found")
    record.missing_acknowledged_at = None
    db_session.commit()
    return {
        "message": f"File '{record.file_path}' dismiss undone, will reappear in discrepancies"
    }


@router.delete("/discrepancies/{file_id}")
def delete_file_record(file_id: int, db_session: Session = Depends(get_db)):
    """Hard-deletes a file record and all associated versions/cart entries."""
    record = db_session.get(models.FilesystemState, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File record not found")
    db_session.query(models.RestoreCart).filter(
        models.RestoreCart.filesystem_state_id == file_id
    ).delete()
    db_session.query(models.FileVersion).filter(
        models.FileVersion.filesystem_state_id == file_id
    ).delete()
    file_path = record.file_path
    db_session.delete(record)
    db_session.commit()
    return {"message": f"File record '{file_path}' permanently deleted"}


# --- Discrepancy Tree & Browse Endpoints ---


@router.get("/discrepancies/tree", response_model=List[TreeNodeSchema])
def get_discrepancies_tree(
    path: Optional[str] = Query(
        default="ROOT", description="Root path to get tree for"
    ),
    db_session: Session = Depends(get_db),
):
    """Returns tree of directories that contain discrepancy files, grouped by source root."""
    from app.api.inventory import get_source_roots

    # Get source roots
    roots = get_source_roots(db_session)

    # Query all discrepancy files
    records = (
        db_session.query(models.FilesystemState)
        .filter(
            models.FilesystemState.is_ignored.is_(False),
            models.FilesystemState.missing_acknowledged_at.is_(None),
            (
                models.FilesystemState.is_deleted.is_(True)
                | models.FilesystemState.sha256_hash.is_(None)
            ),
        )
        .all()
    )

    # Build directory nodes keyed by directory path
    dir_nodes: Dict[str, TreeNodeSchema] = {}
    for record in records:
        directory = (
            record.file_path.rsplit("/", 1)[0] if "/" in record.file_path else ""
        )
        if directory not in dir_nodes:
            dir_nodes[directory] = TreeNodeSchema(
                name=directory.split("/")[-1] or directory or "ROOT",
                path=directory or "ROOT",
                has_children=True,
                children=[],
            )
        dir_nodes[directory].children.append(
            TreeNodeSchema(
                name=record.file_path.split("/")[-1],
                path=record.file_path,
                has_children=False,
            )
        )

    # If path is "ROOT", return top-level nodes grouped by source root
    if path == "ROOT":
        result = []
        seen = set()

        # First add source roots that have discrepancies
        for root in roots:
            root_dirs = [d for d in dir_nodes.keys() if d.startswith(root) or d == root]
            if root_dirs:
                children = [dir_nodes[d] for d in sorted(root_dirs)]
                result.append(
                    TreeNodeSchema(
                        name=root, path=root, has_children=True, children=children
                    )
                )
                seen.update(root_dirs)

        # Add directories that don't match any source root as themselves
        for d in sorted(dir_nodes.keys()):
            if d not in seen:
                result.append(dir_nodes[d])

        return result

    # Return immediate children of the given path
    if path is None:
        return []
    result = []
    for dir_path, node in sorted(dir_nodes.items()):
        if dir_path == path:
            return node.children
        elif dir_path.startswith(path + "/"):
            rel_path = dir_path[len(path) :].strip("/")
            if "/" not in rel_path:
                result.append(node)

    return result

    # Return immediate children of the given path
    result = []
    for dir_path, node in sorted(dir_nodes.items()):
        if dir_path == path:
            # This is the exact node - return its children
            return node.children
        elif dir_path.startswith(path + "/"):
            # This is a subdirectory - check if it's an immediate child
            rel_path = dir_path[len(path) :].strip("/")
            if "/" not in rel_path:
                # Immediate child
                result.append(node)

    return result

    # Return immediate children of the given path
    # Path could be a directory like "/data" - return its children
    result = []
    for dir_path, node in sorted(dir_nodes.items()):
        if dir_path == path:
            # This is the exact node - return its children
            return node.children
        elif dir_path.startswith(path + "/"):
            # This is a subdirectory - check if it's an immediate child
            rel_path = dir_path[len(path) :].strip("/")
            if "/" not in rel_path:
                # Immediate child
                result.append(node)

    return result


@router.get("/discrepancies/browse", response_model=dict)
def browse_discrepancies(
    path: Optional[str] = Query(default="ROOT", description="Directory path to browse"),
    db_session: Session = Depends(get_db),
):
    """Returns discrepancy files and directories under a given directory path."""
    # Query all discrepancy files
    deleted_records = db_session.query(models.FilesystemState).filter(
        models.FilesystemState.is_deleted.is_(True),
        models.FilesystemState.is_ignored.is_(False),
        models.FilesystemState.missing_acknowledged_at.is_(None),
    )

    unhashed_missing = db_session.query(models.FilesystemState).filter(
        models.FilesystemState.sha256_hash.is_(None),
        models.FilesystemState.is_ignored.is_(False),
        models.FilesystemState.is_deleted.is_(False),
        models.FilesystemState.missing_acknowledged_at.is_(None),
    )

    # Batch-load valid version flags
    all_records = deleted_records.all() + unhashed_missing.all()
    record_ids = {r.id for r in all_records}
    ids_with_valid_versions = set()
    if record_ids:
        valid_version_rows = (
            db_session.query(models.FileVersion.filesystem_state_id)
            .join(models.StorageMedia)
            .filter(
                models.FileVersion.filesystem_state_id.in_(record_ids),
                models.StorageMedia.status.in_(["active", "full"]),
            )
            .distinct()
            .all()
        )
        ids_with_valid_versions = {row[0] for row in valid_version_rows}

    # Build a dict of all file paths
    all_paths = {r.file_path: r for r in all_records}

    # Find immediate children under the given path
    results = []
    seen_paths = set()

    for file_path, record in all_paths.items():
        if path == "ROOT":
            # For ROOT, show top-level directories/files
            if "/" in file_path:
                # It's in a subdirectory - get top-level dir
                parts = file_path.strip("/").split("/")
                top_dir = parts[0]
                child_path = "/" + top_dir
                child_name = top_dir
            else:
                # File at root
                child_path = file_path
                child_name = file_path
        else:
            # Check if this file is under the requested path
            if path is None or (
                file_path != path and not file_path.startswith(path + "/")
            ):
                continue

            # Get immediate child relative to path
            path_str = path or ""
            rel_path = file_path[len(path_str) :].strip("/")
            if "/" in rel_path:
                # It's a subdirectory - get immediate child
                child_name = rel_path.split("/")[0]
                child_path = (
                    path_str + "/" + child_name if path_str != "/" else "/" + child_name
                )
            else:
                # It's a file
                child_path = file_path
                child_name = rel_path

        # Skip duplicates
        if child_path in seen_paths:
            continue
        seen_paths.add(child_path)

        # Check if it's a directory or file
        is_dir = any(
            p != child_path and p.startswith(child_path + "/") for p in all_paths
        )

        if is_dir:
            # Count discrepancy files in this directory
            file_count = sum(1 for p in all_paths if p.startswith(child_path + "/"))
            results.append(
                {
                    "name": child_name,
                    "path": child_path,
                    "type": "directory",
                    "has_children": file_count > 0,
                    "discrepancy_count": file_count,
                }
            )
        else:
            # It's a file
            has_valid_versions = record.id in ids_with_valid_versions
            results.append(
                DiscrepancySchema(
                    id=record.id,
                    path=record.file_path,
                    size=record.size,
                    mtime=datetime.fromtimestamp(record.mtime, tz=timezone.utc),
                    last_seen_timestamp=record.last_seen_timestamp,
                    sha256_hash=record.sha256_hash,
                    is_deleted=record.is_deleted,
                    has_versions=has_valid_versions,
                )
            )

    return {"files": results}
