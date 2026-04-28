import json
import os
import shutil
import tarfile
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import func, not_
from sqlalchemy.orm import Session, joinedload

from app.db import models
from app.providers.cloud import CloudStorageProvider
from app.providers.hdd import OfflineHDDProvider
from app.providers.tape import LTOProvider
from app.services.scanner import JobManager


class RangeFile:
    """A file-like object that only reads a specific byte range of a file,
    ensuring strict byte-count delivery for tar alignment."""

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

        # If size is -1 or exceeds remaining, read only what is left
        if size < 0 or size > self.remaining_bytes:
            size = self.remaining_bytes

        chunk_data = self.file_handle.read(size)

        # Alignment Guard: If file was truncated on disk, pad with nulls
        # to prevent corrupting the entire tar archive structure.
        if len(chunk_data) < size:
            logger.error(
                f"Bitstream misalignment: {self.file_path} was truncated during archival. Padding {size - len(chunk_data)} bytes."
            )
            chunk_data += b"\x00" * (size - len(chunk_data))

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

    def normalize_path(self, p: str) -> str:
        """Strips leading slashes and ./ prefixes for robust comparison."""
        p = p.replace("\\", "/")  # Normalize separators
        while p.startswith("/"):
            p = p[1:]
        while p.startswith("./"):
            p = p[2:]
        if p.endswith("/"):
            p = p[:-1]
        return p

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
                mount_base=provider_config.get("mount_path", "/mnt/backup"),
                device_uuid=provider_config.get("device_uuid"),
            )
        elif media_record.media_type == "s3" or media_record.media_type == "cloud":
            return CloudStorageProvider(config=provider_config)

        return None

    def get_unbacked_files(self, db_session: Session):
        """Identifies files that are indexed but lack full version coverage on media."""
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
                break

        return backup_workload

    def _sanitize_recovery_path(
        self, base_destination: str, relative_file_path: str
    ) -> str:
        """Prevents path traversal attacks by validating the final extraction path."""
        cleaned_relative = relative_file_path.lstrip("/")
        absolute_target = os.path.abspath(
            os.path.join(base_destination, cleaned_relative)
        )
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

        storage_provider = self._get_storage_provider(media_record)
        if not storage_provider:
            JobManager.fail_job(
                job_id, f"Unsupported hardware: {media_record.media_type}"
            )
            return

        try:
            if storage_provider.identify_media() != media_record.identifier:
                JobManager.fail_job(job_id, "Hardware mismatch.")
                return

            if not storage_provider.prepare_for_write(media_record.identifier):
                JobManager.fail_job(job_id, "Hardware refused write initialization.")
                return

            archive_filename = (
                f"backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.tar"
            )
            staging_full_path = os.path.join(self.staging_directory, archive_filename)

            processed_bytes = 0
            remaining_to_write = []

            # --- Optimized Deduplication ---
            target_hashes = [
                item["file_state"].sha256_hash
                for item in workload_batch
                if item["file_state"].sha256_hash
            ]
            existing_versions = {}
            SQLITE_VARIABLE_LIMIT = 500
            for i in range(0, len(target_hashes), SQLITE_VARIABLE_LIMIT):
                chunk = target_hashes[i : i + SQLITE_VARIABLE_LIMIT]
                chunk_v = (
                    db_session.query(models.FileVersion)
                    .join(models.FilesystemState)
                    .filter(models.FilesystemState.sha256_hash.in_(chunk))
                    .all()
                )
                for v in chunk_v:
                    existing_versions[
                        (v.file_state.sha256_hash, v.offset_start, v.offset_end)
                    ] = v

            for item in workload_batch:
                file_state = item["file_state"]
                dupe = existing_versions.get(
                    (file_state.sha256_hash, item["offset_start"], item["offset_end"])
                )
                if dupe:
                    db_session.add(
                        models.FileVersion(
                            filesystem_state_id=file_state.id,
                            media_id=dupe.media_id,
                            file_number=dupe.file_number,
                            is_split=dupe.is_split,
                            split_id=dupe.split_id,
                            offset_start=item["offset_start"],
                            offset_end=item["offset_end"],
                        )
                    )
                else:
                    remaining_to_write.append(item)

            # Packaging
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
                        internal_name = self.normalize_path(file_state.file_path)
                        if item["is_split"]:
                            internal_name += f".part_{start}_{end}"

                        if os.path.lexists(file_state.file_path):
                            # Manual TarInfo to ensure strict alignment and bitstream independence
                            tar_info = tar_bundle.gettarinfo(
                                file_state.file_path, arcname=internal_name
                            )

                            if os.path.islink(file_state.file_path):
                                # Preserve Symlinks with their relative targets
                                tar_info.type = tarfile.SYMTYPE
                                tar_info.linkname = os.readlink(file_state.file_path)
                                tar_bundle.addfile(
                                    tar_info
                                )  # Links have no data payload
                            else:
                                # FORCE regular file for everything else (destroys hard-links for reliability)
                                tar_info.type = tarfile.REGTYPE
                                tar_info.linkname = ""
                                tar_info.size = chunk_size

                                with RangeFile(
                                    file_state.file_path, start, chunk_size
                                ) as rh:
                                    tar_bundle.addfile(tar_info, rh)

                        processed_bytes += chunk_size
                        JobManager.update_job(
                            job_id,
                            15.0 + (70.0 * (processed_bytes / safe_divisor)),
                            f"Archiving: {os.path.basename(file_state.file_path)}",
                        )

            if JobManager.is_cancelled(job_id):
                return

            # Finalize Staging
            if remaining_to_write:
                # Sync staging file to disk
                with open(staging_full_path, "a") as f:
                    f.flush()
                    os.fsync(f.fileno())

                JobManager.update_job(
                    job_id, 85.0, f"Streaming bitstream to {media_record.media_type}..."
                )
                with open(staging_full_path, "rb") as final_stream:
                    archive_location_id = storage_provider.write_archive(
                        media_record.identifier, final_stream
                    )
                media_record.bytes_used += os.path.getsize(staging_full_path)

                batch_uuid = str(uuid.uuid4())
                for item in remaining_to_write:
                    db_session.add(
                        models.FileVersion(
                            filesystem_state_id=item["file_state"].id,
                            media_id=media_record.id,
                            file_number=archive_location_id,
                            is_split=item["is_split"],
                            split_id=batch_uuid if item["is_split"] else None,
                            offset_start=item["offset_start"],
                            offset_end=item["offset_end"],
                        )
                    )

            db_session.commit()
            JobManager.complete_job(job_id)
            from app.services.notifications import notification_manager

            notification_manager.notify(
                "Archival Complete",
                f"{media_record.identifier} synchronized.",
                "success",
            )

        except Exception as e:
            logger.exception(f"Archival failed: {e}")
            JobManager.fail_job(job_id, str(e))
        finally:
            if os.path.exists(staging_full_path):
                os.remove(staging_full_path)

    def run_restore(self, db_session: Session, destination_root: str, job_id: int):
        """Orchestrates the retrieval and reassembly of data from storage providers."""
        JobManager.start_job(job_id)
        JobManager.update_job(job_id, 2.0, "Building recovery manifest...")

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

        os.makedirs(destination_root, exist_ok=True)

        media_workload: Dict[int, Dict[str, List[models.FileVersion]]] = {}
        for cart_item in active_cart:
            if not cart_item.file_state.versions:
                continue
            latest_v = max(cart_item.file_state.versions, key=lambda v: v.created_at)
            v_set = (
                [
                    v
                    for v in cart_item.file_state.versions
                    if v.split_id == latest_v.split_id
                ]
                if latest_v.is_split
                else [latest_v]
            )

            for v in v_set:
                if v.media_id not in media_workload:
                    media_workload[v.media_id] = {}
                if v.file_number not in media_workload[v.media_id]:
                    media_workload[v.media_id][v.file_number] = []
                media_workload[v.media_id][v.file_number].append(v)

        processed_bytes = 0
        try:
            for media_id, archive_groups in media_workload.items():
                if JobManager.is_cancelled(job_id):
                    break
                media_record = db_session.get(models.StorageMedia, media_id)
                if not media_record:
                    continue
                provider = self._get_storage_provider(media_record)
                if not provider:
                    continue

                while not provider.check_online():
                    if JobManager.is_cancelled(job_id):
                        break
                    time.sleep(10)

                detected_id = provider.identify_media(allow_intrusive=False)
                # HDD UUID Special Case
                if (
                    media_record.media_type == "hdd"
                    and detected_id != media_record.identifier
                ):
                    cfg = (
                        json.loads(media_record.extra_config)
                        if media_record.extra_config
                        else {}
                    )
                    from app.core.utils import get_path_uuid

                    if get_path_uuid(cfg.get("mount_path", "")) == cfg.get(
                        "device_uuid"
                    ):
                        detected_id = media_record.identifier  # Verified by UUID

                if detected_id != media_record.identifier:
                    JobManager.fail_job(job_id, f"Load {media_record.identifier}")
                    return

                for archive_id in sorted(archive_groups.keys()):
                    if JobManager.is_cancelled(job_id):
                        break
                    target_versions = archive_groups[archive_id]

                    bitstream = provider.read_archive(
                        media_record.identifier, archive_id
                    )
                    tar_mode = "r|*" if media_record.media_type == "tape" else "r:*"

                    with tarfile.open(fileobj=bitstream, mode=tar_mode) as tar_bundle:
                        normalized_map = {}
                        for v in target_versions:
                            name = self.normalize_path(v.file_state.file_path)
                            if v.is_split:
                                name += f".part_{v.offset_start}_{v.offset_end}"
                            normalized_map[name] = v

                        found_count = 0
                        for member in tar_bundle:
                            if JobManager.is_cancelled(job_id):
                                break
                            clean_name = self.normalize_path(member.name)
                            if clean_name in normalized_map:
                                found_count += 1
                                v = normalized_map[clean_name]
                                final_path = self._sanitize_recovery_path(
                                    destination_root, v.file_state.file_path
                                )
                                os.makedirs(os.path.dirname(final_path), exist_ok=True)

                                # Handle based on member type
                                if member.isreg():
                                    src = tar_bundle.extractfile(member)
                                    if src:
                                        mode = (
                                            "r+b"
                                            if os.path.exists(final_path)
                                            else "wb"
                                        )
                                        with open(final_path, mode) as dst:
                                            if v.is_split:
                                                if mode == "wb":
                                                    dst.truncate(v.file_state.size)
                                                dst.seek(v.offset_start)
                                            shutil.copyfileobj(src, dst)

                                        # APPLY METADATA: Restore permissions, ownership, and times
                                        try:
                                            # Copy mode bits
                                            os.chmod(final_path, member.mode)
                                            # Copy timestamps
                                            os.utime(
                                                final_path, (member.mtime, member.mtime)
                                            )
                                            # Attempt to copy ownership (may fail if not root)
                                            try:
                                                os.chown(
                                                    final_path, member.uid, member.gid
                                                )
                                            except Exception:
                                                pass
                                        except Exception as meta_err:
                                            logger.debug(
                                                f"Failed to apply metadata to {final_path}: {meta_err}"
                                            )

                                        processed_bytes += v.offset_end - v.offset_start
                                else:
                                    # Standard tar extraction for symlinks/dirs/etc handles metadata natively
                                    tar_bundle.extract(member, path=destination_root)

                        if found_count == 0:
                            raise FileNotFoundError(f"Archive {archive_id} mismatch")

            if not JobManager.is_cancelled(job_id):
                db_session.query(models.RestoreCart).delete()
                db_session.commit()
                JobManager.complete_job(job_id)

        except Exception as e:
            logger.exception(f"Restore failed: {e}")
            JobManager.fail_job(job_id, str(e))


archiver_manager = ArchiverService()
