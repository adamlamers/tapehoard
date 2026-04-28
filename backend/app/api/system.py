import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

import pathspec
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.db import models
from app.db.database import SessionLocal, get_db
from app.services.scanner import JobManager, scanner_manager
from app.api.schemas import TreeNodeSchema

router = APIRouter(prefix="/system", tags=["System"])

# --- Request/Response Schemas ---


class DashboardStatsSchema(BaseModel):
    total_files_indexed: int
    hashed_files_count: int
    total_data_size: int
    ignored_files_count: int
    ignored_data_size: int
    unprotected_files_count: int
    unprotected_data_size: int
    media_distribution: Dict[str, int]
    last_scan_time: Optional[datetime]
    redundancy_ratio: float


class JobSchema(BaseModel):
    id: int
    job_type: str
    status: str
    progress: float
    current_task: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class FileItemSchema(BaseModel):
    name: str
    path: str
    type: str
    size: Optional[int] = None
    mtime: Optional[float] = None
    ignored: bool = False
    sha256_hash: Optional[str] = None


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


# --- Endpoints ---


@router.get("/dashboard/stats", response_model=DashboardStatsSchema)
def get_dashboard_stats(db_session: Session = Depends(get_db)):
    """Computes high-level system statistics for the overview dashboard."""
    aggregation_sql = text("""
        SELECT
            COUNT(*) as total_count,
            SUM(size) as total_size,
            SUM(CASE WHEN is_ignored = 1 THEN 1 ELSE 0 END) as ignored_count,
            SUM(CASE WHEN is_ignored = 1 THEN size ELSE 0 END) as ignored_size,
            SUM(CASE WHEN is_ignored = 0 AND id NOT IN (SELECT filesystem_state_id FROM file_versions) THEN 1 ELSE 0 END) as unprotected_count,
            SUM(CASE WHEN is_ignored = 0 AND id NOT IN (SELECT filesystem_state_id FROM file_versions) THEN size ELSE 0 END) as unprotected_size,
            SUM(CASE WHEN is_indexed = 1 AND is_ignored = 0 THEN 1 ELSE 0 END) as hashed_count,
            SUM(CASE WHEN is_ignored = 0 THEN 1 ELSE 0 END) as eligible_count
        FROM filesystem_state
    """)

    res = db_session.execute(aggregation_sql).fetchone()
    if res:
        total_count, total_size = res[0] or 0, res[1] or 0
        ignored_count, ignored_size = res[2] or 0, res[3] or 0
        unprotected_count, unprotected_size = res[4] or 0, res[5] or 0
        hashed_count = res[6] or 0
        eligible_count = res[7] or 0
    else:
        total_count = total_size = ignored_count = ignored_size = unprotected_count = (
            unprotected_size
        ) = hashed_count = eligible_count = 0

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

    total_versions = db_session.query(func.count(models.FileVersion.id)).scalar() or 0
    eligible_redundancy_count = max(total_count - ignored_count, 1)
    redundancy_percentage = (total_versions / eligible_redundancy_count) * 100

    return DashboardStatsSchema(
        total_files_indexed=eligible_count,
        hashed_files_count=hashed_count,
        total_data_size=total_size,
        ignored_files_count=ignored_count,
        ignored_data_size=ignored_size,
        unprotected_files_count=unprotected_count,
        unprotected_data_size=unprotected_size,
        media_distribution=media_counts,
        last_scan_time=last_scan.completed_at if last_scan else None,
        redundancy_ratio=round(redundancy_percentage, 1),
    )


@router.get("/jobs", response_model=List[JobSchema])
def list_jobs(limit: int = 10, offset: int = 0, db_session: Session = Depends(get_db)):
    """Returns a paginated list of background archival and discovery jobs."""
    return (
        db_session.query(models.Job)
        .order_by(models.Job.created_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )


@router.get("/jobs/count")
def get_jobs_count(db_session: Session = Depends(get_db)):
    """Returns the total number of jobs recorded in the system."""
    return {"count": db_session.query(models.Job).count()}


@router.get("/jobs/{job_id}", response_model=JobSchema)
def get_job_detail(job_id: int, db_session: Session = Depends(get_db)):
    """Retrieves detailed metadata for a specific job."""
    job_record = db_session.get(models.Job, job_id)
    if not job_record:
        raise HTTPException(status_code=404, detail="Job not found")
    return job_record


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int):
    """Submits a cancellation request for an active job."""
    JobManager.cancel_job(job_id)
    return {"message": "Cancellation request submitted"}


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
        total_files_found=scanner_manager.total_files_found,
        current_path=scanner_manager.current_path,
        is_throttled=scanner_manager.is_throttled,
        hashing_speed=scanner_manager._format_throughput(),
        last_run_time=scanner_manager.last_run_time,
    )


@router.get("/browse", response_model=List[FileItemSchema])
def browse_system_path(
    path: Optional[str] = None, db_session: Session = Depends(get_db)
):
    """Provides a browsable view of the host filesystem for rule configuration."""
    roots = get_source_roots(db_session)
    tracking_rules = db_session.query(models.TrackedSource).all()
    tracking_map = {rule.path: rule.action for rule in tracking_rules}
    exclusion_spec = get_exclusion_spec(db_session)

    if path is None or path == "ROOT":
        results = []
        for root_path in roots:
            if not os.path.exists(root_path):
                continue
            stats = os.stat(root_path)
            # Source roots themselves follow policy
            is_ignored = get_ignored_status(root_path, tracking_map, exclusion_spec)
            results.append(
                FileItemSchema(
                    name=root_path,
                    path=root_path,
                    type="directory",
                    size=stats.st_size,
                    mtime=stats.st_mtime,
                    ignored=is_ignored,
                )
            )
        return results

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Path not found")

    results = []
    try:
        entries = []
        immediate_file_paths = []
        with os.scandir(path) as directory_iterator:
            for entry in directory_iterator:
                entries.append(entry)
                if not entry.is_dir(follow_symlinks=False):
                    immediate_file_paths.append(entry.path)

        # Fetch existing indexed files for ONLY the immediate files in this directory
        indexed_info = {}  # path -> (sha256_hash, is_ignored)
        if immediate_file_paths:
            for i in range(0, len(immediate_file_paths), 900):
                chunk = immediate_file_paths[i : i + 900]
                for f_path, sha256_hash, db_ignored in (
                    db_session.query(
                        models.FilesystemState.file_path,
                        models.FilesystemState.sha256_hash,
                        models.FilesystemState.is_ignored,
                    )
                    .filter(models.FilesystemState.file_path.in_(chunk))
                    .all()
                ):
                    indexed_info[f_path] = (sha256_hash, db_ignored)

        for entry in entries:
            try:
                # Explicitly don't follow symlinks during browsing to show raw state
                file_stats = entry.stat(follow_symlinks=False)

                if entry.path in indexed_info:
                    # If in DB, the DB flag is the source of truth for archival intent
                    is_ignored = indexed_info[entry.path][1]
                    item_hash = indexed_info[entry.path][0]
                else:
                    # If not in DB, calculate intended state based on policy
                    is_ignored = get_ignored_status(
                        entry.path, tracking_map, exclusion_spec
                    )
                    item_hash = None

                results.append(
                    FileItemSchema(
                        name=entry.name,
                        path=entry.path,
                        type="directory"
                        if entry.is_dir(follow_symlinks=False)
                        else "file",
                        size=file_stats.st_size,
                        mtime=file_stats.st_mtime,
                        ignored=is_ignored,
                        sha256_hash=item_hash,
                    )
                )
            except (OSError, FileNotFoundError):
                continue
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    results.sort(key=lambda x: (x.type != "directory", x.name.lower()))
    return results


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
    # 1. Update Tracking Rules and set is_ignored = 0 for inclusions
    for path_to_track in request_data.tracks:
        existing = (
            db_session.query(models.TrackedSource)
            .filter(models.TrackedSource.path == path_to_track)
            .first()
        )
        if existing:
            existing.action = "include"
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
        existing = (
            db_session.query(models.TrackedSource)
            .filter(models.TrackedSource.path == path_to_untrack)
            .first()
        )
        if existing:
            existing.action = "exclude"
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

                tape_provider = LTOProvider(device_path=dev_path)
                state = tape_provider.get_live_state()

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

                    mam_info = state["mam"]
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
                                "tape": state["mam"],
                            },
                        }
                    )
        except Exception as tape_error:
            logger.error(f"Tape discovery failed: {tape_error}")

    # 2. Probe Potential Mount Points
    potential_mounts = ["/mnt", "/media", "/Volumes"]
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

                    # Security & System Filtering
                    try:
                        entry_stats = os.stat(entry.path)
                        if (
                            root_device_id is not None
                            and entry_stats.st_dev == root_device_id
                        ):
                            continue
                    except Exception:
                        continue

                    if entry.path in restricted_paths or entry.path in ignore_list:
                        continue

                    # Check for TapeHoard signature
                    id_file_path = os.path.join(entry.path, ".tapehoard_id")
                    disk_barcode = None
                    if os.path.exists(id_file_path):
                        with open(id_file_path, "r") as f:
                            disk_barcode = f.read().strip()

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
                lambda: os.remove(export_temporary_path)
                if os.path.exists(export_temporary_path)
                else None
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
