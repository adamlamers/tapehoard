import csv
import io
from typing import Dict, List

import pathspec
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.common import FileItemSchema, SettingSchema
from app.db import models
from app.db.database import get_db

router = APIRouter(tags=["System"])


class TestExclusionsRequest(BaseModel):
    patterns: str
    limit: int = 10


class TestExclusionsResponse(BaseModel):
    total_files: int
    total_size: int
    matched_count: int
    matched_size: int
    sample: List[FileItemSchema]


@router.get("/settings", response_model=Dict[str, str], operation_id="get_settings")
def get_settings(db_session: Session = Depends(get_db)):
    """Retrieves all global system configuration key-value pairs."""
    settings_records = db_session.query(models.SystemSetting).all()
    return {record.key: record.value for record in settings_records}


@router.post("/settings", operation_id="update_settings")
def update_settings(setting_data: SettingSchema, db_session: Session = Depends(get_db)):
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


@router.post(
    "/settings/test-exclusions",
    response_model=TestExclusionsResponse,
    operation_id="test_exclusions",
)
def test_exclusions(
    request_data: TestExclusionsRequest, db_session: Session = Depends(get_db)
):
    """Tests exclusion patterns against the current filesystem index."""
    patterns = [p.strip() for p in request_data.patterns.splitlines() if p.strip()]
    if not patterns:
        return TestExclusionsResponse(
            total_files=0, total_size=0, matched_count=0, matched_size=0, sample=[]
        )

    spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)

    all_files = (
        db_session.query(models.FilesystemState)
        .filter(models.FilesystemState.is_deleted.is_(False))
        .all()
    )

    total_size = 0
    matched = []
    matched_size = 0
    for file_record in all_files:
        total_size += file_record.size or 0
        if spec.match_file(file_record.file_path):
            matched_size += file_record.size or 0
            matched.append(
                FileItemSchema(
                    name=file_record.file_path.split("/")[-1],
                    path=file_record.file_path,
                    type="file",
                    size=file_record.size,
                    mtime=file_record.mtime,
                    ignored=file_record.is_ignored,
                    sha256_hash=file_record.sha256_hash,
                )
            )

    total_files = len(all_files)
    matched_count = len(matched)
    sample = matched[: request_data.limit]

    return TestExclusionsResponse(
        total_files=total_files,
        total_size=total_size,
        matched_count=matched_count,
        matched_size=matched_size,
        sample=sample,
    )


@router.post(
    "/settings/test-exclusions/download",
    operation_id="download_exclusion_report",
)
def download_exclusion_report(
    request_data: TestExclusionsRequest, db_session: Session = Depends(get_db)
):
    """Generates a CSV report of files matched by exclusion patterns."""
    patterns = [p.strip() for p in request_data.patterns.splitlines() if p.strip()]
    if not patterns:
        raise HTTPException(status_code=400, detail="No patterns provided")

    spec = pathspec.PathSpec.from_lines("gitwildmatch", patterns)

    all_files = (
        db_session.query(models.FilesystemState)
        .filter(models.FilesystemState.is_deleted.is_(False))
        .all()
    )

    matched = []
    for file_record in all_files:
        if spec.match_file(file_record.file_path):
            matched.append(file_record)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["path", "size", "mtime", "sha256_hash"])
    for file_record in matched:
        writer.writerow(
            [
                file_record.file_path,
                file_record.size,
                file_record.mtime,
                file_record.sha256_hash or "",
            ]
        )

    csv_bytes = output.getvalue().encode("utf-8")
    output.close()

    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=exclusion_report.csv"},
    )
