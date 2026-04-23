import os
import tarfile
import json
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import not_
from app.db import models
from app.services.scanner import JobManager
from app.providers.hdd import OfflineHDDProvider
from app.providers.tape import LTOProvider
from app.providers.cloud import CloudStorageProvider


class ArchiverService:
    def __init__(self, staging_dir: str = "/staging"):
        self.staging_dir = staging_dir
        if not os.path.exists(self.staging_dir):
            try:
                os.makedirs(self.staging_dir, exist_ok=True)
            except Exception:
                # Fallback for local dev without /staging
                self.staging_dir = os.path.join(os.getcwd(), "staging_area")
                os.makedirs(self.staging_dir, exist_ok=True)

    def _get_provider(self, media: models.StorageMedia):
        config: Dict[str, Any] = {}
        if media.extra_config:
            try:
                config = json.loads(media.extra_config)
            except Exception:
                pass

        if media.media_type == "tape":
            return LTOProvider(device_path=config.get("device_path", "/dev/nst0"))
        elif media.media_type == "hdd":
            return OfflineHDDProvider(
                mount_base=config.get("mount_path", "/mnt/backup")
            )
        elif media.media_type == "cloud":
            return CloudStorageProvider(config=config)
        return None

    def get_eligible_files(self, db: Session) -> List[models.FilesystemState]:
        """Returns files that are indexed but have no version on any media"""
        return (
            db.query(models.FilesystemState)
            .filter(
                models.FilesystemState.is_indexed,
                not_(models.FilesystemState.is_ignored),
                not_(models.FilesystemState.versions.any()),
            )
            .all()
        )

    def create_backup_set(
        self, db: Session, media_id: int, max_bytes: Optional[int] = None
    ) -> List[models.FilesystemState]:
        """Selects a batch of files that fit on the media's remaining capacity"""
        media = db.query(models.StorageMedia).get(media_id)
        if not media:
            return []

        remaining_capacity = media.capacity - media.bytes_used
        if max_bytes:
            remaining_capacity = min(remaining_capacity, max_bytes)

        eligible = self.get_eligible_files(db)

        # Simple Greedy Bin-Packing
        backup_set = []
        current_size = 0

        for f in eligible:
            if current_size + f.size <= remaining_capacity:
                backup_set.append(f)
                current_size += f.size

        return backup_set

    def run_backup(self, db: Session, media_id: int, job_id: int):
        media = db.query(models.StorageMedia).get(media_id)
        if not media:
            JobManager.fail_job(job_id, "Media not found")
            return

        JobManager.start_job(job_id)
        JobManager.update_job(
            job_id, 5.0, f"Preparing backup set for {media.identifier}..."
        )

        backup_set = self.create_backup_set(db, media_id)
        if not backup_set:
            JobManager.complete_job(job_id)
            logger.info("No eligible files for backup")
            return

        total_bytes = sum(f.size for f in backup_set)
        JobManager.update_job(
            job_id,
            10.0,
            f"Backing up {len(backup_set)} files ({total_bytes / 1e9:.2f} GB)...",
        )

        provider = self._get_provider(media)
        if not provider:
            JobManager.fail_job(job_id, f"Unsupported media type: {media.media_type}")
            return

        # 1. Identify Media
        current_id = provider.identify_media()
        if current_id != media.identifier:
            JobManager.fail_job(
                job_id,
                f"Media mismatch! Insert {media.identifier} (Found: {current_id})",
            )
            return

        if not provider.prepare_for_write(media.identifier):
            JobManager.fail_job(job_id, "Failed to prepare media for writing")
            return

        # 2. Create Archive in Staging
        # For now, we package everything into one tar for this job
        archive_name = (
            f"backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.tar"
        )
        staging_path = os.path.join(self.staging_dir, archive_name)

        try:
            processed_bytes = 0
            with tarfile.open(staging_path, "w") as tar:
                for f_state in backup_set:
                    if JobManager.is_cancelled(job_id):
                        break

                    JobManager.update_job(
                        job_id,
                        15.0 + (70.0 * (processed_bytes / total_bytes)),
                        f"Archiving: {os.path.basename(f_state.file_path)}",
                    )

                    if os.path.exists(f_state.file_path):
                        tar.add(
                            f_state.file_path, arcname=f_state.file_path.lstrip("/")
                        )

                    processed_bytes += f_state.size

            if JobManager.is_cancelled(job_id):
                if os.path.exists(staging_path):
                    os.remove(staging_path)
                return

            # 3. Stream to Provider
            JobManager.update_job(
                job_id, 85.0, f"Streaming archive to {media.media_type}..."
            )
            with open(staging_path, "rb") as archive_stream:
                location_id = provider.write_archive(media.identifier, archive_stream)

            # 4. Finalize & Record
            provider.finalize_media(media.identifier)

            # Update database records
            for f_state in backup_set:
                version = models.FileVersion(
                    filesystem_state_id=f_state.id,
                    media_id=media.id,
                    file_number=location_id,
                )
                db.add(version)

            media.bytes_used += os.path.getsize(staging_path)
            db.commit()

            JobManager.complete_job(job_id)
            logger.info(f"Backup job {job_id} completed successfully")

        except Exception as e:
            logger.exception(f"Backup failed: {e}")
            JobManager.fail_job(job_id, str(e))
        finally:
            if os.path.exists(staging_path):
                os.remove(staging_path)


archiver_manager = ArchiverService()
