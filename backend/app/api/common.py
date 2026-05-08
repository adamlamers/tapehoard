import json
import os
from datetime import datetime
from typing import Dict, List, Optional

import pathspec
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import models


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
    return pathspec.PathSpec.from_lines("gitignore", exclusion_patterns)


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


def get_ignored_by_policy(
    absolute_path: str,
    exclusion_spec: Optional[pathspec.PathSpec],
) -> bool:
    """Determines if a path is excluded by global policy only (ignores manual tracking rules)."""
    if exclusion_spec and exclusion_spec.match_file(absolute_path):
        return True
    return False


def recompute_exclusion_policy(db_session: Session) -> None:
    """Recomputes is_ignored_by_policy and effective is_ignored for all indexed files."""
    exclusion_spec = get_exclusion_spec(db_session)
    tracking_rules = db_session.query(models.TrackedSource).all()
    tracking_map = {rule.path: rule.action for rule in tracking_rules}

    # Update is_ignored_by_policy in batches
    all_files = db_session.query(
        models.FilesystemState.id, models.FilesystemState.file_path
    ).all()

    for file_id, file_path in all_files:
        is_ignored_by_policy = get_ignored_by_policy(file_path, exclusion_spec)
        is_ignored = get_ignored_status(file_path, tracking_map, exclusion_spec)

        db_session.execute(
            text(
                "UPDATE filesystem_state SET is_ignored_by_policy = :policy, is_ignored = :ignored WHERE id = :id"
            ),
            {"policy": is_ignored_by_policy, "ignored": is_ignored, "id": file_id},
        )

    db_session.commit()


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


def _get_last_scan_time(db_session: Session) -> Optional[datetime]:
    """Returns the completion time of the most recent successful SCAN job."""
    last_scan = (
        db_session.query(models.Job)
        .filter(models.Job.job_type == "SCAN", models.Job.status == "COMPLETED")
        .order_by(models.Job.completed_at.desc())
        .first()
    )
    return last_scan.completed_at if last_scan else None


def escape_fts5_query(query: str) -> str:
    """Escapes a query string for safe use in SQLite FTS5 MATCH expressions.

    FTS5 has special syntax characters that cause errors if not escaped:
    - Double quotes need to be doubled (" becomes "")
    - Leading dots, hyphens, etc. have special meaning
    - Asterisk (*) enables prefix matching when outside quotes
    - The trigram tokenizer works best with literal phrase matching

    Returns a query that will match any file path containing the search term.
    """
    # Escape double quotes by doubling them
    escaped = query.replace('"', '""')

    # Always wrap in double quotes for literal matching
    # This treats special characters (., -, etc.) as literals
    # The * after the closing quote enables prefix matching
    return f'"{escaped}"*'


# --- Shared Schemas ---


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


class StagingInfoSchema(BaseModel):
    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int


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


class BatchTrackRequest(BaseModel):
    tracks: List[str] = []
    untracks: List[str] = []


class TapeOperationRequest(BaseModel):
    device_path: str
    secure_erase: bool = False


class TapeFileNumberResponse(BaseModel):
    device_path: str
    file_number: int


class TapeOperationResponse(BaseModel):
    success: bool
    message: str
    device_path: str
