import os
import tarfile
import json
import uuid
import time
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from loguru import logger
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import not_, func
from app.db import models
from app.services.scanner import JobManager
from app.providers.hdd import OfflineHDDProvider
from app.providers.tape import LTOProvider
from app.providers.cloud import CloudStorageProvider


class RangeFile:
    """A file-like object that only reads a specific byte range of a file."""

    def __init__(self, file_path: str, offset_start: int, length: int):
        self.file_path = file_path
        self.offset_start = offset_start
        self.length = length
        self.remaining_bytes = length
        self.file_handle = open(file_path, "rb")
        self.file_handle.seek(offset_start)

    def read(self, size: int = -1) -> bytes:
        if self.remaining_bytes <= 0:
            return b""

        bytes_to_read = self.remaining_bytes
        if size > 0:
            bytes_to_read = min(size, self.remaining_bytes)

        chunk_data = self.file_handle.read(bytes_to_read)
        self.remaining_bytes -= len(chunk_data)
        return chunk_data

    def close(self):
        self.file_handle.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class ArchiverService:
    """Handles data archival to physical media and recovery from storage providers."""

    def __init__(self, staging_directory: str = "/staging"):
        self.staging_directory = staging_directory
        if not os.path.exists(self.staging_directory):
            try:
                os.makedirs(self.staging_directory, exist_ok=True)
            except OSError:
                # Fallback for local development environments
                self.staging_directory = os.path.join(os.getcwd(), "staging_area")
                os.makedirs(self.staging_directory, exist_ok=True)

    def _get_storage_provider(self, media_record: models.StorageMedia):
        """Initializes the appropriate hardware provider based on media type."""
        provider_config: Dict[str, Any] = {}
        if media_record.extra_config:
            try:
                provider_config = json.loads(media_record.extra_config)
            except json.JSONDecodeError:
                logger.error(
                    f"Failed to decode config for media {media_record.identifier}"
                )

        if media_record.media_type == "tape":
            return LTOProvider(
                device_path=provider_config.get("device_path", "/dev/nst0"),
                encryption_key=provider_config.get("encryption_key"),
            )
        elif media_record.media_type == "hdd":
            return OfflineHDDProvider(
                mount_base=provider_config.get("mount_path", "/mnt/backup")
            )
        elif media_record.media_type == "cloud":
            return CloudStorageProvider(config=provider_config)

        return None

    def get_unbacked_files(self, db_session: Session):
        """Identifies files that are indexed but lack full version coverage on media."""
        # Calculate covered size per file using an optimized subquery
        coverage_subquery = (
            db_session.query(
                models.FileVersion.filesystem_state_id,
                func.sum(
                    models.FileVersion.offset_end - models.FileVersion.offset_start
                ).label("covered_bytes"),
            )
            .group_by(models.FileVersion.filesystem_state_id)
            .subquery()
        )

        return (
            db_session.query(
                models.FilesystemState,
                func.coalesce(coverage_subquery.c.covered_bytes, 0).label(
                    "covered_bytes"
                ),
            )
            .outerjoin(
                coverage_subquery,
                models.FilesystemState.id == coverage_subquery.c.filesystem_state_id,
            )
            .filter(
                models.FilesystemState.is_indexed,
                not_(models.FilesystemState.is_ignored),
                (coverage_subquery.c.covered_bytes.is_(None))
                | (coverage_subquery.c.covered_bytes < models.FilesystemState.size),
            )
            .yield_per(1000)
        )

    def assemble_backup_batch(
        self, db_session: Session, media_id: int, max_batch_size: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Selects a workload batch that fits within the available media capacity."""
        media_record = db_session.get(models.StorageMedia, media_id)
        if not media_record:
            return []

        remaining_capacity = media_record.capacity - media_record.bytes_used
        if max_batch_size:
            remaining_capacity = min(remaining_capacity, max_batch_size)

        unbacked_files = self.get_unbacked_files(db_session)
        backup_workload = []
        accumulated_size = 0
        MINIMUM_FRAGMENT_SIZE = 100 * 1024 * 1024  # 100MB

        for file_state, covered_bytes in unbacked_files:
            if accumulated_size >= remaining_capacity:
                break

            remaining_file_bytes = file_state.size - covered_bytes

            # 0-byte file handling
            if file_state.size == 0:
                has_any_version = (
                    db_session.query(models.FileVersion)
                    .filter(models.FileVersion.filesystem_state_id == file_state.id)
                    .first()
                    is not None
                )
                if not has_any_version:
                    backup_workload.append(
                        {
                            "file_state": file_state,
                            "offset_start": 0,
                            "offset_end": 0,
                            "is_split": False,
                        }
                    )
                continue

            available_space = remaining_capacity - accumulated_size
            if remaining_file_bytes <= available_space:
                backup_workload.append(
                    {
                        "file_state": file_state,
                        "offset_start": covered_bytes,
                        "offset_end": file_state.size,
                        "is_split": covered_bytes > 0,
                    }
                )
                accumulated_size += remaining_file_bytes
            elif available_space >= MINIMUM_FRAGMENT_SIZE:
                backup_workload.append(
                    {
                        "file_state": file_state,
                        "offset_start": covered_bytes,
                        "offset_end": covered_bytes + available_space,
                        "is_split": True,
                    }
                )
                accumulated_size += available_space
                break  # Media filled

        return backup_workload

    def _sanitize_recovery_path(
        self, base_destination: str, relative_file_path: str
    ) -> str:
        """Prevents path traversal attacks by validating the final extraction path."""
        # Strip leading slashes to ensure it's relative
        cleaned_relative = relative_file_path.lstrip("/")
        absolute_target = os.path.abspath(
            os.path.join(base_destination, cleaned_relative)
        )

        # Verify target is still within the destination root
        if not absolute_target.startswith(os.path.abspath(base_destination)):
            raise PermissionError(
                f"Restricted path traversal detected: {relative_file_path}"
            )

        return absolute_target

    def run_backup(self, db_session: Session, media_id: int, job_id: int):
        """Orchestrates the archival of a data batch to a storage provider."""
        media_record = db_session.get(models.StorageMedia, media_id)
        if not media_record:
            JobManager.fail_job(job_id, "Media record not found.")
            return

        JobManager.start_job(job_id)
        JobManager.update_job(
            job_id, 5.0, f"Calculating backup set for {media_record.identifier}..."
        )

        workload_batch = self.assemble_backup_batch(db_session, media_id)
        if not workload_batch:
            JobManager.complete_job(job_id)
            return

        total_payload_bytes = sum(
            item["offset_end"] - item["offset_start"] for item in workload_batch
        )
        safe_divisor = max(total_payload_bytes, 1)

        JobManager.update_job(
            job_id,
            10.0,
            f"Preparing {len(workload_batch)} items ({total_payload_bytes / 1e9:.2f} GB)...",
        )

        storage_provider = self._get_storage_provider(media_record)
        if not storage_provider:
            JobManager.fail_job(
                job_id, f"Unsupported hardware: {media_record.media_type}"
            )
            return

        # Hardware Validation
        try:
            detected_id = storage_provider.identify_media()
            if detected_id != media_record.identifier:
                JobManager.fail_job(
                    job_id,
                    f"Hardware mismatch. Insert {media_record.identifier} (Found: {detected_id})",
                )
                return

            if not storage_provider.prepare_for_write(media_record.identifier):
                JobManager.fail_job(job_id, "Hardware refused write initialization.")
                return

            # Staging Logic
            archive_filename = (
                f"backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.tar"
            )
            staging_full_path = os.path.join(self.staging_directory, archive_filename)

            processed_bytes = 0
            remaining_to_write = []

            # --- Optimized Deduplication Check (Chunked for SQLite limits) ---
            target_hashes = [
                item["file_state"].sha256_hash
                for item in workload_batch
                if item["file_state"].sha256_hash
            ]

            existing_versions = {}
            # Chunking to avoid (sqlite3.OperationalError) too many SQL variables
            SQLITE_VARIABLE_LIMIT = 500
            for i in range(0, len(target_hashes), SQLITE_VARIABLE_LIMIT):
                chunk = target_hashes[i : i + SQLITE_VARIABLE_LIMIT]
                chunk_versions = (
                    db_session.query(models.FileVersion)
                    .join(models.FilesystemState)
                    .filter(models.FilesystemState.sha256_hash.in_(chunk))
                    .all()
                )
                for version in chunk_versions:
                    key = (
                        version.file_state.sha256_hash,
                        version.offset_start,
                        version.offset_end,
                    )
                    existing_versions[key] = version

            for item in workload_batch:
                file_state = item["file_state"]
                dedupe_key = (
                    file_state.sha256_hash,
                    item["offset_start"],
                    item["offset_end"],
                )
                duplicate_version = existing_versions.get(dedupe_key)

                if duplicate_version:
                    logger.info(
                        f"Deduplicating {file_state.file_path} -> Linked to existing storage"
                    )
                    new_version = models.FileVersion(
                        filesystem_state_id=file_state.id,
                        media_id=duplicate_version.media_id,
                        file_number=duplicate_version.file_number,
                        is_split=duplicate_version.is_split,
                        split_id=duplicate_version.split_id,
                        offset_start=item["offset_start"],
                        offset_end=item["offset_end"],
                    )
                    db_session.add(new_version)
                    continue

                remaining_to_write.append(item)

            # Packaging Logic
            if remaining_to_write:
                with tarfile.open(staging_full_path, "w") as tar_bundle:
                    for item in remaining_to_write:
                        if JobManager.is_cancelled(job_id):
                            break

                        file_state, start, end = (
                            item["file_state"],
                            item["offset_start"],
                            item["offset_end"],
                        )
                        chunk_size = end - start

                        JobManager.update_job(
                            job_id,
                            15.0 + (70.0 * (processed_bytes / safe_divisor)),
                            f"Archiving: {os.path.basename(file_state.file_path)}",
                        )

                        if os.path.exists(file_state.file_path):
                            archive_internal_name = file_state.file_path.lstrip("/")
                            if item["is_split"]:
                                archive_internal_name = (
                                    f"{archive_internal_name}.part_{start}_{end}"
                                )

                            tar_info = tar_bundle.gettarinfo(
                                file_state.file_path, arcname=archive_internal_name
                            )
                            tar_info.size = chunk_size

                            with RangeFile(
                                file_state.file_path, start, chunk_size
                            ) as range_handle:
                                tar_bundle.addfile(tar_info, range_handle)

                        processed_bytes += chunk_size

            if JobManager.is_cancelled(job_id):
                if os.path.exists(staging_full_path):
                    os.remove(staging_full_path)
                return

            # Hardware Streaming
            archive_location_id = "DEDUPLICATED"
            if remaining_to_write:
                JobManager.update_job(
                    job_id, 85.0, f"Streaming bitstream to {media_record.media_type}..."
                )
                with open(staging_full_path, "rb") as final_stream:
                    archive_location_id = storage_provider.write_archive(
                        media_record.identifier, final_stream
                    )
                media_record.bytes_used += os.path.getsize(staging_full_path)

            # Finalize Batch
            storage_provider.finalize_media(media_record.identifier)
            batch_uuid = str(uuid.uuid4())

            for item in remaining_to_write:
                new_v = models.FileVersion(
                    filesystem_state_id=item["file_state"].id,
                    media_id=media_record.id,
                    file_number=archive_location_id,
                    is_split=item["is_split"],
                    split_id=batch_uuid if item["is_split"] else None,
                    offset_start=item["offset_start"],
                    offset_end=item["offset_end"],
                )
                db_session.add(new_v)

            db_session.commit()
            JobManager.complete_job(job_id)

            from app.services.notifications import notification_manager

            notification_manager.notify(
                "Archival Complete",
                f"{media_record.identifier} workload synchronized.",
                "success",
            )

        except Exception as backup_error:
            logger.exception(f"Archival process failed: {backup_error}")
            JobManager.fail_job(job_id, str(backup_error))
        finally:
            if os.path.exists(staging_full_path):
                os.remove(staging_full_path)

    def run_restore(self, db_session: Session, destination_root: str, job_id: int):
        """Orchestrates the retrieval and reassembly of data from storage providers."""
        JobManager.start_job(job_id)
        JobManager.update_job(job_id, 2.0, "Building recovery manifest...")

        # --- Optimized Manifest Generation (Eradicate N+1) ---
        # Fetch cart items AND all their versions in a single pass
        active_cart = (
            db_session.query(models.RestoreCart)
            .options(
                joinedload(models.RestoreCart.file_state).joinedload(
                    models.FilesystemState.versions
                )
            )
            .all()
        )

        if not active_cart:
            JobManager.complete_job(job_id)
            return

        total_bytes_to_recover = sum(item.file_state.size for item in active_cart)
        safe_divisor = max(total_bytes_to_recover, 1)

        os.makedirs(destination_root, exist_ok=True)

        # Group tasks by hardware availability
        media_workload: Dict[int, Dict[str, List[models.FileVersion]]] = {}
        for cart_item in active_cart:
            latest_versions = sorted(
                cart_item.file_state.versions, key=lambda v: v.created_at, reverse=True
            )
            if not latest_versions:
                continue

            # Just retrieve all parts of the versions we find
            for version_record in latest_versions:
                m_id, f_num = version_record.media_id, version_record.file_number
                if m_id not in media_workload:
                    media_workload[m_id] = {}
                if f_num not in media_workload[m_id]:
                    media_workload[m_id][f_num] = []
                media_workload[m_id][f_num].append(version_record)

        processed_bytes = 0
        try:
            for media_id, archive_groups in media_workload.items():
                if JobManager.is_cancelled(job_id):
                    break

                media_record = db_session.get(models.StorageMedia, media_id)
                provider = self._get_storage_provider(media_record)
                if not media_record or not provider:
                    continue

                # Hardware Readiness Check
                JobManager.update_job(
                    job_id, 5.0, f"Requesting media: {media_record.identifier}"
                )
                detected_id = provider.identify_media()

                while detected_id != media_record.identifier:
                    if JobManager.is_cancelled(job_id):
                        break
                    from app.services.notifications import notification_manager

                    notification_manager.notify(
                        "Media Needed",
                        f"Load {media_record.identifier} to continue recovery.",
                        "warning",
                    )
                    time.sleep(10)
                    detected_id = provider.identify_media()

                if JobManager.is_cancelled(job_id):
                    break

                # Sequential Extraction Pass
                for archive_id in sorted(archive_groups.keys()):
                    if JobManager.is_cancelled(job_id):
                        break

                    target_versions = archive_groups[archive_id]
                    JobManager.update_job(
                        job_id,
                        10.0 + (80.0 * (processed_bytes / safe_divisor)),
                        f"Extracting from {media_record.identifier}",
                    )

                    bitstream = provider.read_archive(
                        media_record.identifier, archive_id
                    )
                    with tarfile.open(fileobj=bitstream, mode="r|*") as tar_bundle:
                        # Build internal names map
                        name_to_version = {}
                        for v in target_versions:
                            internal_name = v.file_state.file_path.lstrip("/")
                            if v.is_split:
                                internal_name = f"{internal_name}.part_{v.offset_start}_{v.offset_end}"
                            name_to_version[internal_name] = v

                        for member in tar_bundle:
                            if JobManager.is_cancelled(job_id):
                                break
                            if member.name in name_to_version:
                                version = name_to_version[member.name]
                                final_system_path = self._sanitize_recovery_path(
                                    destination_root, version.file_state.file_path
                                )

                                os.makedirs(
                                    os.path.dirname(final_system_path), exist_ok=True
                                )

                                if version.is_split:
                                    # Concurrent Chunk Reassembly
                                    write_mode = (
                                        "r+b"
                                        if os.path.exists(final_system_path)
                                        else "wb"
                                    )
                                    with open(
                                        final_system_path, write_mode
                                    ) as target_file:
                                        if write_mode == "wb":
                                            target_file.truncate(
                                                version.file_state.size
                                            )
                                        target_file.seek(version.offset_start)
                                        chunk_handle = tar_bundle.extractfile(member)
                                        if chunk_handle:
                                            target_file.write(chunk_handle.read())
                                else:
                                    tar_bundle.extract(member, path=destination_root)

                                processed_bytes += (
                                    version.offset_end - version.offset_start
                                )

            if not JobManager.is_cancelled(job_id):
                db_session.query(models.RestoreCart).delete()
                db_session.commit()
                JobManager.complete_job(job_id)
                from app.services.notifications import notification_manager

                notification_manager.notify(
                    "Recovery Success",
                    f"Data extracted to {destination_root}",
                    "success",
                )

        except Exception as restore_error:
            logger.exception(f"Recovery failed: {restore_error}")
            JobManager.fail_job(job_id, str(restore_error))


archiver_manager = ArchiverService()
