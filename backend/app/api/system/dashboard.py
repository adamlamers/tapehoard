from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.api.common import DashboardStatsSchema
from sqlalchemy import func, text
from app.db import models

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
