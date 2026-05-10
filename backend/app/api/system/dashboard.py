import shutil

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.common import DashboardStatsSchema, StagingInfoSchema
from app.core.config import settings
from app.db import models
from app.db.database import get_db

router = APIRouter(tags=["System"])


def _get_redundancy_target(db_session: Session) -> int:
    setting = (
        db_session.query(models.SystemSetting)
        .filter_by(key="redundancy_target")
        .first()
    )
    if setting:
        try:
            v = int(setting.value)
            if v >= 1:
                return v
        except (ValueError, TypeError):
            pass
    return 1


@router.get(
    "/dashboard/stats",
    response_model=DashboardStatsSchema,
    operation_id="get_dashboard_stats",
)
def get_dashboard_stats(db_session: Session = Depends(get_db)):
    """Computes high-level system statistics for the overview dashboard."""
    redundancy_target = _get_redundancy_target(db_session)

    aggregation_sql = text("""
        SELECT
            COUNT(*) as total_count,
            COALESCE(SUM(size), 0) as total_size,
            COALESCE(SUM(CASE WHEN is_ignored = 1 THEN 1 ELSE 0 END), 0) as ignored_count,
            COALESCE(SUM(CASE WHEN is_ignored = 1 THEN size ELSE 0 END), 0) as ignored_size,
            COALESCE(SUM(CASE WHEN sha256_hash IS NOT NULL AND is_ignored = 0 AND is_deleted = 0 THEN 1 ELSE 0 END), 0) as hashed_count,
            COALESCE(SUM(CASE WHEN is_ignored = 0 AND is_deleted = 0 THEN 1 ELSE 0 END), 0) as eligible_count,
            COALESCE(SUM(CASE WHEN is_deleted = 1 AND missing_acknowledged_at IS NULL AND is_ignored = 0 THEN 1 ELSE 0 END), 0) as active_discrepancies_count,
            -- Bytes actually written to active/full/offline media (includes redundant copies, excludes failed/retired media)
            COALESCE((
                SELECT SUM(fv.offset_end - fv.offset_start)
                FROM file_versions fv
                JOIN storage_media sm ON sm.id = fv.media_id
                WHERE sm.status IN ('active', 'full', 'offline')
            ), 0) as archived_size,
            -- Files with fewer complete copies than the redundancy target
            COALESCE(SUM(CASE WHEN is_ignored = 0 AND is_deleted = 0 AND redundancy_count < :target THEN 1 ELSE 0 END), 0) as unprotected_count,
            COALESCE(SUM(CASE WHEN is_ignored = 0 AND is_deleted = 0 AND redundancy_count < :target THEN size ELSE 0 END), 0) as unprotected_size
        FROM filesystem_state
    """)

    res = db_session.execute(aggregation_sql, {"target": redundancy_target}).fetchone()
    if res:
        total_size = res[1]
        ignored_count = res[2]
        ignored_size = res[3]
        hashed_count = res[4]
        eligible_count = res[5]
        active_discrepancies_count = res[6]
        archived_size = res[7]
        unprotected_count = res[8]
        unprotected_size = res[9]
    else:
        total_size = 0
        ignored_count = 0
        ignored_size = 0
        hashed_count = 0
        eligible_count = 0
        active_discrepancies_count = 0
        archived_size = 0
        unprotected_count = 0
        unprotected_size = 0

    media_counts = {
        "LTO": db_session.query(models.StorageMedia)
        .filter(models.StorageMedia.media_type == "lto_tape")
        .count(),
        "HDD": db_session.query(models.StorageMedia)
        .filter(models.StorageMedia.media_type == "local_hdd")
        .count(),
        "Cloud": db_session.query(models.StorageMedia)
        .filter(
            models.StorageMedia.media_type.in_(["s3_compat", "google_drive", "dropbox"])
        )
        .count(),
    }

    last_scan = (
        db_session.query(models.Job)
        .filter(models.Job.job_type == "SCAN", models.Job.status == "COMPLETED")
        .order_by(models.Job.completed_at.desc())
        .first()
    )

    eligible_size = max(total_size - ignored_size, 1)
    # Redundancy ratio can exceed 100% when multiple copies exist
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
        redundancy_target=redundancy_target,
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
