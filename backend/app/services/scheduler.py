from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.db import models
from app.services.scanner import scanner_manager, JobManager
from app.services.archiver import archiver_manager


class SchedulerService:
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.jobs = {}

    def start(self):
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Scheduler service started")
            self.load_schedules()

    def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Scheduler service stopped")

    def load_schedules(self):
        """Loads and schedules jobs from database settings"""
        db = SessionLocal()
        try:
            # 1. Scan Schedule
            scan_cron = self._get_setting(db, "schedule_scan")
            if scan_cron:
                self.add_job("system_scan", self.run_system_scan, scan_cron)

            # 2. Archival Schedule
            # Note: This would typically pick the first active media or a designated 'auto' media
            archival_cron = self._get_setting(db, "schedule_archival")
            if archival_cron:
                self.add_job("system_archival", self.run_system_archival, archival_cron)
        finally:
            db.close()

    def _get_setting(self, db: Session, key: str) -> str:
        setting = (
            db.query(models.SystemSetting)
            .filter(models.SystemSetting.key == key)
            .first()
        )
        return setting.value if setting else ""

    def add_job(self, job_id, func, cron_expression):
        """Adds or updates a job with a cron expression"""
        try:
            # Remove existing if it exists
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)

            if cron_expression.strip():
                self.scheduler.add_job(
                    func,
                    CronTrigger.from_crontab(cron_expression),
                    id=job_id,
                    replace_existing=True,
                )
                logger.info(f"Scheduled job {job_id} with cron: {cron_expression}")
        except Exception as e:
            logger.error(f"Failed to schedule job {job_id}: {e}")

    def run_system_scan(self):
        logger.info("Starting scheduled system scan...")
        db = SessionLocal()
        try:
            if not scanner_manager.is_running:
                job = JobManager.create_job(db, "SCAN")
                scanner_manager.scan_sources(db, job_id=job.id)
        except Exception as e:
            logger.error(f"Scheduled scan failed: {e}")
        finally:
            db.close()

    def run_system_archival(self):
        logger.info("Starting scheduled archival job...")
        db = SessionLocal()
        try:
            # Look for a designated primary target
            primary_id = self._get_setting(db, "primary_archival_target")

            media = None
            if primary_id:
                media = (
                    db.query(models.StorageMedia)
                    .filter(
                        models.StorageMedia.id == int(primary_id),
                        models.StorageMedia.status == "active",
                    )
                    .first()
                )

            if not media:
                # Fallback: pick first available 'active' media if no primary set
                media = (
                    db.query(models.StorageMedia)
                    .filter(models.StorageMedia.status == "active")
                    .first()
                )

            if media:
                job = JobManager.create_job(db, "BACKUP")
                archiver_manager.run_backup(db, media.id, job_id=job.id)
            else:
                logger.warning("No suitable media found for scheduled archival")
        except Exception as e:
            logger.error(f"Scheduled archival failed: {e}")
        finally:
            db.close()


scheduler_manager = SchedulerService()
