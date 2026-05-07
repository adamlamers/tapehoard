import shutil

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.common import DashboardStatsSchema, StagingInfoSchema
from app.core.config import settings
from app.db import models
from app.db.database import get_db

router = APIRouter(tags=["System"])


@router.get(
    "/dashboard/stats",
    response_model=DashboardStatsSchema,
    operation_id="get_dashboard_stats",
)
def get_dashboard_stats(db_session: Session = Depends(get_db)):
    """Computes high-level system statistics for the overview dashboard."""
    aggregation_sql = text("""
        SELECT
            COUNT(*) as total_count,
            SUM(size) as total_size,
            SUM(CASE WHEN is_ignored = 1 THEN 1 ELSE 0 END) as ignored_count,
            SUM(CASE WHEN is_ignored = 1 THEN size ELSE 0 END) as ignored_size,
            SUM(CASE WHEN is_ignored = 0 AND is_deleted = 0 AND
                COALESCE((SELECT SUM(fv.offset_end - fv.offset_start)
                          FROM file_versions fv
                          JOIN storage_media sm ON sm.id = fv.media_id
                          WHERE fv.filesystem_state_id = filesystem_state.id
                          AND sm.status IN ('active', 'full')), 0) < filesystem_state.size
            THEN 1 ELSE 0 END) as unprotected_count,
            SUM(CASE WHEN is_ignored = 0 AND is_deleted = 0 AND
                COALESCE((SELECT SUM(fv.offset_end - fv.offset_start)
                          FROM file_versions fv
                          JOIN storage_media sm ON sm.id = fv.media_id
                          WHERE fv.filesystem_state_id = filesystem_state.id
                          AND sm.status IN ('active', 'full')), 0) < filesystem_state.size
            THEN filesystem_state.size - COALESCE((SELECT SUM(fv.offset_end - fv.offset_start)
                          FROM file_versions fv
                          JOIN storage_media sm ON sm.id = fv.media_id
                          WHERE fv.filesystem_state_id = filesystem_state.id
                          AND sm.status IN ('active', 'full')), 0)
            ELSE 0 END) as unprotected_size,
            SUM(CASE WHEN sha256_hash IS NOT NULL AND is_ignored = 0 AND is_deleted = 0 THEN 1 ELSE 0 END) as hashed_count,
            SUM(CASE WHEN is_ignored = 0 AND is_deleted = 0 THEN 1 ELSE 0 END) as eligible_count,
            COALESCE((SELECT SUM(fv.offset_end - fv.offset_start)
                      FROM file_versions fv
                      JOIN storage_media sm ON sm.id = fv.media_id
                      WHERE sm.status IN ('active', 'full')), 0) as archived_size,
            SUM(CASE WHEN is_deleted = 1 THEN 1 ELSE 0 END) as missing_count,
            SUM(CASE WHEN is_deleted = 1 AND missing_acknowledged_at IS NULL AND is_ignored = 0 THEN 1 ELSE 0 END) as active_discrepancies_count
        FROM filesystem_state
    """)

    res = db_session.execute(aggregation_sql).fetchone()
    if res:
        total_size = res[1] or 0
        ignored_count = res[2] or 0
        ignored_size = res[3] or 0
        unprotected_count = res[4] or 0
        unprotected_size = res[5] or 0
        hashed_count = res[6] or 0
        eligible_count = res[7] or 0
        archived_size = res[8] or 0
        active_discrepancies_count = res[10] or 0
    else:
        total_size = 0
        ignored_count = 0
        ignored_size = 0
        unprotected_count = 0
        unprotected_size = 0
        hashed_count = 0
        eligible_count = 0
        archived_size = 0
        active_discrepancies_count = 0

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

    eligible_size = max(total_size - ignored_size, 1)
    redundancy_percentage = (archived_size / eligible_size) * 100

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


@router.get(
    "/staging/info", response_model=StagingInfoSchema, operation_id="get_staging_info"
)
def get_staging_info():
    """Returns disk usage information for the backup staging directory."""
    path = settings.staging_directory
    try:
        usage = shutil.disk_usage(path)
        return StagingInfoSchema(
            path=path,
            total_bytes=usage.total,
            used_bytes=usage.used,
            free_bytes=usage.free,
        )
    except OSError:
        # Fallback: if the configured path doesn't exist yet, check its parent
        parent = path if path == "/" else path.rsplit("/", 1)[0] or "/"
        try:
            usage = shutil.disk_usage(parent)
            return StagingInfoSchema(
                path=path,
                total_bytes=usage.total,
                used_bytes=usage.used,
                free_bytes=usage.free,
            )
        except OSError:
            return StagingInfoSchema(
                path=path,
                total_bytes=0,
                used_bytes=0,
                free_bytes=0,
            )
