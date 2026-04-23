from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
import os
import json
import asyncio
from datetime import datetime
from typing import List, Optional, Dict, Tuple
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from app.db.database import get_db, SessionLocal
from app.db import models
from app.services.scanner import scanner_manager, JobManager
import pathspec

router = APIRouter(prefix="/system", tags=["System"])


# --- Models ---
class DashboardStatsSchema(BaseModel):
    total_files_indexed: int
    total_data_size: int
    tracked_paths_count: int
    unprotected_files_count: int
    unprotected_data_size: int
    ignored_files_count: int
    ignored_data_size: int
    redundancy_ratio: float
    last_scan_time: Optional[datetime]
    media_distribution: Dict[str, int]


class JobSchema(BaseModel):
    id: int
    job_type: str
    status: str
    progress: float
    current_task: Optional[str]
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class FileItemSchema(BaseModel):
    name: str
    path: str
    type: str
    size: Optional[int] = None
    mtime: Optional[float] = None
    tracked: bool = False
    ignored: bool = False


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
    total_files_found: int
    current_path: str
    last_run_time: Optional[datetime] = None


class SettingSchema(BaseModel):
    key: str
    value: str


# --- Helpers ---
def get_source_roots(db: Session) -> List[str]:
    setting = (
        db.query(models.SystemSetting)
        .filter(models.SystemSetting.key == "source_roots")
        .first()
    )
    if setting:
        try:
            return json.loads(setting.value)
        except Exception:
            return [setting.value]
    local_source = os.path.abspath(os.path.join(os.getcwd(), "..", "source_data"))
    if os.path.exists(local_source):
        return [local_source]
    return ["/source_data"]


def get_exclusion_spec(db: Session) -> Optional[pathspec.PathSpec]:
    setting = (
        db.query(models.SystemSetting)
        .filter(models.SystemSetting.key == "global_exclusions")
        .first()
    )
    if not setting or not setting.value.strip():
        return None
    patterns = [p.strip() for p in setting.value.splitlines() if p.strip()]
    return pathspec.PathSpec.from_lines("gitwildmatch", patterns)


def get_tracking_status(
    path: str, tracking_map: Dict[str, str], spec: Optional[pathspec.PathSpec]
) -> Tuple[bool, bool]:
    is_ignored = False
    if spec and spec.match_file(path):
        is_ignored = True
    applicable_rules = []
    for rule_path, action in tracking_map.items():
        if path == rule_path or path.startswith(rule_path + "/"):
            applicable_rules.append((len(rule_path), action))
    if not applicable_rules:
        return not is_ignored, is_ignored
    applicable_rules.sort(key=lambda x: x[0], reverse=True)
    is_tracked = applicable_rules[0][1] == "include"
    return is_tracked, is_ignored


# --- Endpoints ---


@router.get("/dashboard/stats", response_model=DashboardStatsSchema)
def get_dashboard_stats(db: Session = Depends(get_db)):
    agg_sql = text("""
        SELECT
            COUNT(*) as total_count,
            SUM(size) as total_size,
            SUM(CASE WHEN is_ignored = 1 THEN 1 ELSE 0 END) as ignored_count,
            SUM(CASE WHEN is_ignored = 1 THEN size ELSE 0 END) as ignored_size,
            SUM(CASE WHEN is_ignored = 0 AND is_indexed = 1 AND id NOT IN (SELECT filesystem_state_id FROM file_versions) THEN 1 ELSE 0 END) as unprotected_count,
            SUM(CASE WHEN is_ignored = 0 AND is_indexed = 1 AND id NOT IN (SELECT filesystem_state_id FROM file_versions) THEN size ELSE 0 END) as unprotected_size
        FROM filesystem_state
    """)

    result = db.execute(agg_sql).fetchone()

    if result:
        total_count = result[0] or 0
        total_size = result[1] or 0
        ignored_count = result[2] or 0
        ignored_size = result[3] or 0
        unprotected_count = result[4] or 0
        unprotected_size = result[5] or 0
    else:
        total_count = total_size = ignored_count = ignored_size = unprotected_count = (
            unprotected_size
        ) = 0

    tracked_paths = (
        db.query(func.count(models.TrackedSource.id))
        .filter(models.TrackedSource.action == "include")
        .scalar()
        or 0
    )

    total_versions = db.query(func.count(models.FileVersion.id)).scalar() or 0
    eligible_count = total_count - ignored_count
    redundancy = total_versions / eligible_count if eligible_count > 0 else 0.0

    media_dist = {"LTO": 0, "HDD": 0, "Cloud": 0}
    media_counts = (
        db.query(models.StorageMedia.media_type, func.count(models.StorageMedia.id))
        .group_by(models.StorageMedia.media_type)
        .all()
    )
    for mtype, count in media_counts:
        media_dist[mtype.upper()] = count

    return DashboardStatsSchema(
        total_files_indexed=total_count,
        total_data_size=total_size,
        tracked_paths_count=tracked_paths,
        unprotected_files_count=unprotected_count,
        unprotected_data_size=unprotected_size,
        ignored_files_count=ignored_count,
        ignored_data_size=ignored_size,
        redundancy_ratio=round(redundancy, 2),
        last_scan_time=scanner_manager.last_run_time,
        media_distribution=media_dist,
    )


@router.get("/jobs", response_model=List[JobSchema])
def list_jobs(limit: int = 50, db: Session = Depends(get_db)):
    return (
        db.query(models.Job).order_by(models.Job.created_at.desc()).limit(limit).all()
    )


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    JobManager.cancel_job(job_id)
    return {"message": "Cancellation request submitted"}


@router.get("/jobs/stream")
async def stream_jobs():
    async def event_generator():
        while True:
            db = SessionLocal()
            try:
                active_jobs = (
                    db.query(models.Job)
                    .filter(models.Job.status.in_(["RUNNING", "PENDING"]))
                    .all()
                )
                data = [JobSchema.model_validate(j).model_dump() for j in active_jobs]
                for job in data:
                    for key in ["started_at", "completed_at", "created_at"]:
                        if job[key] and isinstance(job[key], datetime):
                            job[key] = job[key].isoformat()
                yield f"data: {json.dumps(data)}\n\n"
            finally:
                db.close()
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/scan")
def trigger_scan(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if scanner_manager.is_running:
        raise HTTPException(status_code=400, detail="Scan already in progress")
    job = JobManager.create_job(db, "SCAN")

    def run_scan():
        db_inner = SessionLocal()
        try:
            scanner_manager.scan_sources(db_inner, job_id=job.id)
        finally:
            db_inner.close()

    background_tasks.add_task(run_scan)
    return {"message": "Scan started", "job_id": job.id}


@router.get("/scan/status", response_model=ScanStatusSchema)
def get_scan_status():
    return ScanStatusSchema(
        is_running=scanner_manager.is_running,
        files_processed=scanner_manager.files_processed,
        files_hashed=scanner_manager.files_hashed,
        total_files_found=scanner_manager.total_files_found,
        current_path=scanner_manager.current_path,
        last_run_time=scanner_manager.last_run_time,
    )


@router.get("/browse", response_model=List[FileItemSchema])
def browse_path(path: Optional[str] = None, db: Session = Depends(get_db)):
    roots = get_source_roots(db)
    tracking_map = {s.path: s.action for s in db.query(models.TrackedSource).all()}
    spec = get_exclusion_spec(db)
    if path is None or path == "ROOT":
        results = []
        for root in roots:
            if not os.path.exists(root):
                continue
            stats = os.stat(root)
            tracked, ignored = get_tracking_status(root, tracking_map, spec)
            results.append(
                FileItemSchema(
                    name=root,
                    path=root,
                    type="directory",
                    size=stats.st_size,
                    mtime=stats.st_mtime,
                    tracked=tracked,
                    ignored=ignored,
                )
            )
        return results
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Not found")
    results = []
    with os.scandir(path) as it:
        for entry in it:
            try:
                stats = entry.stat(follow_symlinks=False)
                tracked, ignored = get_tracking_status(entry.path, tracking_map, spec)
                results.append(
                    FileItemSchema(
                        name=entry.name,
                        path=entry.path,
                        type="directory" if entry.is_dir() else "file",
                        size=stats.st_size,
                        mtime=stats.st_mtime,
                        tracked=tracked,
                        ignored=ignored,
                    )
                )
            except Exception:
                continue
    results.sort(key=lambda x: (x.type != "directory", x.name.lower()))
    return results


@router.post("/track/batch")
def track_batch(req: BatchTrackRequest, db: Session = Depends(get_db)):
    for path in req.tracks:
        existing = (
            db.query(models.TrackedSource)
            .filter(models.TrackedSource.path == path)
            .first()
        )
        if existing:
            existing.action = "include"
        else:
            db.add(models.TrackedSource(path=path, action="include"))
    for path in req.untracks:
        existing = (
            db.query(models.TrackedSource)
            .filter(models.TrackedSource.path == path)
            .first()
        )
        if existing:
            existing.action = "exclude"
        else:
            db.add(models.TrackedSource(path=path, action="exclude"))
    db.commit()
    return {"message": "Updated"}


@router.get("/settings", response_model=Dict[str, str])
def get_settings(db: Session = Depends(get_db)):
    all_settings = db.query(models.SystemSetting).all()
    return {s.key: s.value for s in all_settings}


@router.post("/settings")
def update_setting(req: SettingSchema, db: Session = Depends(get_db)):
    setting = (
        db.query(models.SystemSetting)
        .filter(models.SystemSetting.key == req.key)
        .first()
    )
    if setting:
        setting.value = req.value
    else:
        db.add(models.SystemSetting(key=req.key, value=req.value))
    db.commit()
    return {"message": "Updated"}


@router.get("/tree")
def get_tree(path: Optional[str] = None, db: Session = Depends(get_db)):
    roots = get_source_roots(db)
    if path is None or path == "ROOT":
        return [{"name": r, "path": r, "has_children": True} for r in roots]
    return []
