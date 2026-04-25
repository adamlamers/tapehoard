import os
import tarfile
import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import not_, func
from app.db import models
from app.services.scanner import JobManager
from app.providers.hdd import OfflineHDDProvider
from app.providers.tape import LTOProvider
from app.providers.cloud import CloudStorageProvider


class RangeFile:
    """A file-like object that only reads a specific range of a file."""

    def __init__(self, file_path: str, offset_start: int, length: int):
        self.file_path = file_path
        self.offset_start = offset_start
        self.length = length
        self.remaining = length
        self.file = open(file_path, "rb")
        self.file.seek(offset_start)

    def read(self, size: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""

        to_read = self.remaining
        if size > 0:
            to_read = min(size, self.remaining)

        data = self.file.read(to_read)
        self.remaining -= len(data)
        return data

    def close(self):
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


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
            return LTOProvider(
                device_path=config.get("device_path", "/dev/nst0"),
                encryption_key=config.get("encryption_key"),
            )
        elif media.media_type == "hdd":
            return OfflineHDDProvider(
                mount_base=config.get("mount_path", "/mnt/backup")
            )
        elif media.media_type == "cloud":
            return CloudStorageProvider(config=config)
        return None

    def get_eligible_files(self, db: Session):
        """Returns files that are indexed but have no version, or are partially backed up"""
        # Optimized query to find files that are not fully covered by their versions
        # A file is eligible if sum(offset_end - offset_start) < size

        subquery = (
            db.query(
                models.FileVersion.filesystem_state_id,
                func.sum(
                    models.FileVersion.offset_end - models.FileVersion.offset_start
                ).label("covered_size"),
            )
            .group_by(models.FileVersion.filesystem_state_id)
            .subquery()
        )

        return (
            db.query(models.FilesystemState)
            .outerjoin(
                subquery, models.FilesystemState.id == subquery.c.filesystem_state_id
            )
            .filter(
                models.FilesystemState.is_indexed,
                not_(models.FilesystemState.is_ignored),
                (subquery.c.covered_size.is_(None))
                | (subquery.c.covered_size < models.FilesystemState.size),
            )
            .yield_per(1000)
        )

    def create_backup_set(
        self, db: Session, media_id: int, max_bytes: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Selects a batch of files/chunks that fit on the media's remaining capacity"""
        media = db.query(models.StorageMedia).get(media_id)
        if not media:
            return []

        remaining_capacity = media.capacity - media.bytes_used
        if max_bytes:
            remaining_capacity = min(remaining_capacity, max_bytes)

        eligible = self.get_eligible_files(db)

        backup_set = []
        current_size = 0

        # We need at least some space to make it worthwhile
        MIN_CHUNK_SIZE = 100 * 1024 * 1024  # 100MB

        for f in eligible:
            if current_size >= remaining_capacity:
                break

            # Calculate how much of this file is already backed up
            # For simplicity, we assume we always backup from the end of the last chunk
            covered_size = (
                db.query(
                    func.sum(
                        models.FileVersion.offset_end - models.FileVersion.offset_start
                    )
                )
                .filter(models.FileVersion.filesystem_state_id == f.id)
                .scalar()
                or 0
            )

            remaining_file_size = f.size - covered_size

            # Allow 0-byte files if they have no versions yet
            if remaining_file_size <= 0 and f.size > 0:
                continue
            if f.size == 0:
                # Check if it already has a version to avoid infinite loop
                has_version = (
                    db.query(models.FileVersion)
                    .filter(models.FileVersion.filesystem_state_id == f.id)
                    .first()
                    is not None
                )
                if has_version:
                    continue

            space_left = remaining_capacity - current_size

            if remaining_file_size <= space_left:
                # Entire remaining file fits
                backup_set.append(
                    {
                        "file_state": f,
                        "offset_start": covered_size,
                        "offset_end": f.size,
                        "is_split": covered_size
                        > 0,  # It's a split if we already had parts
                    }
                )
                current_size += remaining_file_size
            elif space_left >= MIN_CHUNK_SIZE:
                # Only part of it fits
                backup_set.append(
                    {
                        "file_state": f,
                        "offset_start": covered_size,
                        "offset_end": covered_size + space_left,
                        "is_split": True,
                    }
                )
                current_size += space_left
                # Once we split a file to fill the media, we are done with this set
                break

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

        total_bytes = sum(
            item["offset_end"] - item["offset_start"] for item in backup_set
        )
        divisor = max(total_bytes, 1)

        JobManager.update_job(
            job_id,
            10.0,
            f"Backing up {len(backup_set)} items ({total_bytes / 1e9:.2f} GB)...",
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
        archive_name = (
            f"backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.tar"
        )
        staging_path = os.path.join(self.staging_dir, archive_name)

        try:
            processed_bytes = 0
            # Identify files that can be deduplicated (hash already exists on media)
            deduped_items = []
            remaining_backup_set = []

            for item in backup_set:
                f_state = item["file_state"]
                # Look for an existing version with the same hash
                if f_state.sha256_hash:
                    existing_v = (
                        db.query(models.FileVersion)
                        .join(models.FilesystemState)
                        .filter(
                            models.FilesystemState.sha256_hash == f_state.sha256_hash,
                            models.FileVersion.offset_start == item["offset_start"],
                            models.FileVersion.offset_end == item["offset_end"],
                        )
                        .first()
                    )

                    if existing_v:
                        logger.info(
                            f"Deduplicating {f_state.file_path} -> existing version on {existing_v.media_id}"
                        )
                        deduped_items.append(
                            {
                                "file_state": f_state,
                                "existing_v": existing_v,
                                "item": item,
                            }
                        )
                        continue

                remaining_backup_set.append(item)

            if remaining_backup_set:
                with tarfile.open(staging_path, "w") as tar:
                    for item in remaining_backup_set:
                        if JobManager.is_cancelled(job_id):
                            break

                        f_state = item["file_state"]
                        start = item["offset_start"]
                        end = item["offset_end"]
                        chunk_size = end - start

                        JobManager.update_job(
                            job_id,
                            15.0 + (70.0 * (processed_bytes / divisor)),
                            f"Archiving: {os.path.basename(f_state.file_path)} (Part {start}-{end})",
                        )
                        if os.path.exists(f_state.file_path):
                            # Use RangeFile to stream only the requested part
                            arcname = f_state.file_path.lstrip("/")
                            if item["is_split"]:
                                # Append part info to arcname if it's split
                                arcname = f"{arcname}.part_{start}_{end}"

                            tarinfo = tar.gettarinfo(f_state.file_path, arcname=arcname)
                            tarinfo.size = chunk_size  # Override size

                            with RangeFile(f_state.file_path, start, chunk_size) as rf:
                                tar.addfile(tarinfo, rf)

                        processed_bytes += chunk_size

            if JobManager.is_cancelled(job_id):
                if os.path.exists(staging_path):
                    os.remove(staging_path)
                return

            # 3. Stream to Provider (if there's anything to stream)
            location_id = "DEDUPLICATED"
            if remaining_backup_set:
                JobManager.update_job(
                    job_id, 85.0, f"Streaming archive to {media.media_type}..."
                )
                with open(staging_path, "rb") as archive_stream:
                    location_id = provider.write_archive(
                        media.identifier, archive_stream
                    )
                media.bytes_used += os.path.getsize(staging_path)

            # 4. Finalize & Record
            provider.finalize_media(media.identifier)

            # Update database records for written files
            split_id = str(uuid.uuid4())
            for item in remaining_backup_set:
                f_state = item["file_state"]
                version = models.FileVersion(
                    filesystem_state_id=f_state.id,
                    media_id=media.id,
                    file_number=location_id,
                    is_split=item["is_split"],
                    split_id=split_id if item["is_split"] else None,
                    offset_start=item["offset_start"],
                    offset_end=item["offset_end"],
                )
                db.add(version)

            # Update database records for deduped files
            for dedup in deduped_items:
                f_state = dedup["file_state"]
                existing_v = dedup["existing_v"]
                item = dedup["item"]

                version = models.FileVersion(
                    filesystem_state_id=f_state.id,
                    media_id=existing_v.media_id,
                    file_number=existing_v.file_number,
                    is_split=existing_v.is_split,
                    split_id=existing_v.split_id,
                    offset_start=item["offset_start"],
                    offset_end=item["offset_end"],
                )
                db.add(version)

            db.commit()

            JobManager.complete_job(job_id)
            logger.info(f"Backup job {job_id} completed successfully")
            from app.services.notifications import notification_manager

            notification_manager.notify(
                "Archival Completed",
                f"Archival job to {media.identifier} finished. {len(backup_set)} items written.",
                "success",
            )

        except Exception as e:
            logger.exception(f"Backup failed: {e}")
            JobManager.fail_job(job_id, str(e))
            from app.services.notifications import notification_manager

            notification_manager.notify(
                "Archival Failed",
                f"Archival job to {media.identifier} failed: {str(e)}",
                "failure",
            )
        finally:
            if os.path.exists(staging_path):
                os.remove(staging_path)

    def run_restore(self, db: Session, destination: str, job_id: int):
        JobManager.start_job(job_id)
        JobManager.update_job(job_id, 2.0, "Preparing restore manifest...")

        cart_items = db.query(models.RestoreCart).all()
        if not cart_items:
            JobManager.complete_job(job_id)
            logger.info("No items in restore cart")
            return

        total_bytes = sum(item.file_state.size for item in cart_items)
        divisor = max(total_bytes, 1)

        JobManager.update_job(
            job_id, 5.0, f"Restoring {len(cart_items)} files to {destination}..."
        )

        # Ensure destination exists
        os.makedirs(destination, exist_ok=True)

        # Group by media -> location_id -> [FileVersion]
        # We need FileVersion objects to know the offsets
        media_tasks = {}  # media_id -> {location_id: [FileVersion]}

        for item in cart_items:
            if not item.file_state.versions:
                continue

            # Find the most recent "full" version or set of parts
            # For now, we'll just pick all parts of the FIRST version group we find
            # Actually, let's just get ALL versions and filter the logic
            # Simpler: Get the latest versions for this file
            versions = (
                db.query(models.FileVersion)
                .filter(models.FileVersion.filesystem_state_id == item.file_state.id)
                .order_by(models.FileVersion.created_at.desc())
                .all()
            )

            if not versions:
                continue

            # If the latest one is split, we might need multiple.
            # For now, let's just restore WHATEVER we have versions for.
            for v in versions:
                if v.media_id not in media_tasks:
                    media_tasks[v.media_id] = {}
                if v.file_number not in media_tasks[v.media_id]:
                    media_tasks[v.media_id][v.file_number] = []
                media_tasks[v.media_id][v.file_number].append(v)

        processed_bytes = 0

        try:
            for media_id, locations in media_tasks.items():
                if JobManager.is_cancelled(job_id):
                    break

                media = db.query(models.StorageMedia).get(media_id)
                if not media:
                    continue

                provider = self._get_provider(media)
                if not provider:
                    continue

                # Check media
                JobManager.update_job(
                    job_id,
                    10.0 + (80.0 * (processed_bytes / divisor)),
                    f"Waiting for {media.identifier}...",
                )
                current_id = provider.identify_media()
                if current_id != media.identifier:
                    raise Exception(
                        f"Media mismatch! Insert {media.identifier} (Found: {current_id})"
                    )

                # Sort location IDs for sequential access
                for loc_id in sorted(locations.keys()):
                    v_list = locations[loc_id]
                    if JobManager.is_cancelled(job_id):
                        break

                    JobManager.update_job(
                        job_id,
                        10.0 + (80.0 * (processed_bytes / divisor)),
                        f"Extracting from {media.identifier} (Archive {loc_id})...",
                    )

                    archive_stream = provider.read_archive(media.identifier, loc_id)

                    # Extract using tarfile
                    with tarfile.open(fileobj=archive_stream, mode="r|*") as tar:
                        # Build a map of what's in this tar that we want
                        # We use part names for split files
                        wanted_map = {}  # arcname -> FileVersion
                        for v in v_list:
                            arcname = v.file_state.file_path.lstrip("/")
                            if v.is_split:
                                arcname = (
                                    f"{arcname}.part_{v.offset_start}_{v.offset_end}"
                                )
                            wanted_map[arcname] = v

                        for member in tar:
                            if JobManager.is_cancelled(job_id):
                                break

                            if member.name in wanted_map:
                                v = wanted_map[member.name]
                                final_path = os.path.join(
                                    destination, v.file_state.file_path.lstrip("/")
                                )

                                # Ensure dir exists
                                os.makedirs(os.path.dirname(final_path), exist_ok=True)

                                if v.is_split:
                                    # Atomic reassembly: Write to specific offset
                                    # Use 'r+b' to allow seeking if file exists, 'wb' if not
                                    mode = "r+b" if os.path.exists(final_path) else "wb"
                                    with open(final_path, mode) as f:
                                        if mode == "wb":
                                            # Pre-allocate if possible or just seek
                                            f.truncate(v.file_state.size)
                                        f.seek(v.offset_start)
                                        # Extract the member bytes
                                        f_in = tar.extractfile(member)
                                        if f_in:
                                            f.write(f_in.read())
                                else:
                                    # Standard extraction
                                    tar.extract(member, path=destination)

                                processed_bytes += v.offset_end - v.offset_start

            if not JobManager.is_cancelled(job_id):
                JobManager.complete_job(job_id)
                # Clear cart
                db.query(models.RestoreCart).delete()
                db.commit()
                logger.info(f"Restore job {job_id} completed successfully")
                from app.services.notifications import notification_manager

                notification_manager.notify(
                    "Recovery Completed",
                    f"Data recovery to {destination} finished successfully.",
                    "success",
                )

        except Exception as e:
            logger.exception(f"Restore failed: {e}")
            JobManager.fail_job(job_id, str(e))
            from app.services.notifications import notification_manager

            notification_manager.notify(
                "Recovery Failed",
                f"Data recovery to {destination} failed: {str(e)}",
                "failure",
            )


archiver_manager = ArchiverService()
