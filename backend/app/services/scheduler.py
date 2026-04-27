from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db import models
from app.services.scanner import scanner_manager, JobManager
from app.services.archiver import archiver_manager


class SchedulerService:
    """Orchestrates automated discovery scans and archival jobs."""

    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.jobs = {}

    def start(self):
        """Initializes and starts the background scheduler."""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Scheduler service initiated.")
            self.load_schedules()

    def stop(self):
        """Gracefully shuts down the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Scheduler service stopped.")

    def reload(self):
        """Reloads all schedules from the current database settings."""
        logger.info("Reloading automated schedules...")
        self.load_schedules()

    def load_schedules(self):
        """Loads and schedules jobs from database settings."""
        with SessionLocal() as db_session:
            # 1. System Scan Schedule
            scan_cron_expression = self._get_setting(db_session, "schedule_scan")
            if scan_cron_expression:
                self.add_job("system_scan", self.run_system_scan, scan_cron_expression)
            else:
                self.remove_job("system_scan")

            # 2. Media Archival Schedule
            archival_cron_expression = self._get_setting(
                db_session, "schedule_archival"
            )
            if archival_cron_expression:
                self.add_job(
                    "system_archival",
                    self.run_system_archival,
                    archival_cron_expression,
                )
            else:
                self.remove_job("system_archival")

    def _get_setting(self, db_session: Session, setting_key: str) -> str:
        """Retrieves a system setting string value."""
        setting_record = (
            db_session.query(models.SystemSetting)
            .filter(models.SystemSetting.key == setting_key)
            .first()
        )
        return setting_record.value if setting_record else ""

    def add_job(self, job_id: str, job_function, cron_expression: str):
        """Adds or updates a job with a standard crontab expression."""
        try:
            # Standardize empty strings
            clean_cron = cron_expression.strip()
            if not clean_cron:
                self.remove_job(job_id)
                return

            self.scheduler.add_job(
                job_function,
                CronTrigger.from_crontab(clean_cron),
                id=job_id,
                replace_existing=True,
            )
            logger.info(f"Scheduled job '{job_id}' with policy: {clean_cron}")
        except Exception as schedule_error:
            logger.error(f"Failed to schedule job '{job_id}': {schedule_error}")

    def remove_job(self, job_id: str):
        """Removes a job from the scheduler if it exists."""
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            logger.info(f"Removed scheduled job '{job_id}'.")

    def run_system_scan(self):
        """Background task for automated metadata discovery."""
        logger.info("Triggering scheduled discovery scan...")
        if scanner_manager.is_running:
            logger.warning("Scheduled scan skipped: Discovery already in progress.")
            return

        with SessionLocal() as db_session:
            try:
                job_record = JobManager.create_job(db_session, "SCAN")
                scanner_manager.scan_sources(db_session, job_id=job_record.id)
            except Exception as scan_error:
                logger.error(f"Scheduled scan failed: {scan_error}")

    def run_system_archival(self):
        """Background task for automated data archival to highest priority media."""
        logger.info("Triggering scheduled media archival...")

        with SessionLocal() as db_session:
            try:
                # Identify the highest priority 'active' media that is currently online
                # Note: prioritized by priority_index (lower is higher priority)
                target_media = (
                    db_session.query(models.StorageMedia)
                    .filter(models.StorageMedia.status == "active")
                    .order_by(models.StorageMedia.priority_index.asc())
                    .all()
                )

                found_media = None
                for media in target_media:
                    # Perform a real hardware check
                    provider = archiver_manager._get_storage_provider(media)
                    if (
                        provider
                        and provider.check_online()
                        and provider.identify_media(allow_intrusive=False)
                        == media.identifier
                    ):
                        found_media = media
                        break

                if found_media:
                    logger.info(
                        f"Scheduled archival targeting media: {found_media.identifier}"
                    )
                    job_record = JobManager.create_job(db_session, "BACKUP")
                    archiver_manager.run_backup(
                        db_session, found_media.id, job_id=job_record.id
                    )
                else:
                    logger.warning(
                        "Scheduled archival skipped: No prioritized active media is currently online."
                    )
            except Exception as archival_error:
                logger.error(f"Scheduled archival failed: {archival_error}")


scheduler_manager = SchedulerService()
