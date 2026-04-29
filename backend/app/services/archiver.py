import json
import os
import shutil
import subprocess
import sys
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
        import os

        provider_map = {
            LTOProvider.provider_id: LTOProvider,
            OfflineHDDProvider.provider_id: OfflineHDDProvider,
            CloudStorageProvider.provider_id: CloudStorageProvider,
            # Backwards compatibility for legacy DB records
            "tape": LTOProvider,
            "hdd": OfflineHDDProvider,
            "cloud": CloudStorageProvider,
            "s3": CloudStorageProvider,
        }

        if os.environ.get("TAPEHOARD_TEST_MODE") == "true":
            from app.providers.mock import MockLTOProvider

            provider_map[MockLTOProvider.provider_id] = (
                MockLTOProvider  # ty: ignore[invalid-assignment]
            )

        provider_cls = provider_map.get(media_record.media_type)
        if not provider_cls:
            return None

        provider_config: Dict[str, Any] = {}
        if media_record.extra_config:
            try:
                provider_config = json.loads(media_record.extra_config)
            except json.JSONDecodeError:
                logger.error(
                    f"Failed to decode config for media {media_record.identifier}"
                )

        # Standards fallback for legacy config keys
        if provider_cls == OfflineHDDProvider and "mount_path" not in provider_config:
            # Older DBs might have used mount_base in some contexts, though hdd used mount_path in code
            pass

        return provider_cls(config=provider_config)

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
            elif (
                file_state.size > media_record.capacity
                and available_space >= MINIMUM_FRAGMENT_SIZE
            ):
                # ONLY split if the file is physically larger than a single piece of media
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
            else:
                # File is larger than remaining space but smaller than total media capacity.
                # Skip it for this media to avoid unnecessary fragmentation.
                continue

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

        # --- Tar Chunking Logic ---
        # Ensure at least 100 archives per tape to improve restoration granularity.
        # Max chunk size = capacity / 100.
        MAX_CHUNK_SIZE = media_record.capacity // 100
        if MAX_CHUNK_SIZE < 100 * 1024 * 1024:  # Minimum 100MB chunk
            MAX_CHUNK_SIZE = 100 * 1024 * 1024

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

            processed_bytes = 0
            batch_uuid = str(uuid.uuid4())

            # Split workload into chunks for packaging
            chunks = []
            current_chunk = []
            current_chunk_size = 0
            for item in workload_batch:
                item_size = item["offset_end"] - item["offset_start"]

                # CHUNKING LOGIC:
                # 1. If adding this item exceeds MAX_CHUNK_SIZE...
                # 2. AND we already have items in the current chunk...
                # 3. AND it's not a random access provider...
                # ... then finalize the current chunk.
                if (
                    current_chunk_size + item_size > MAX_CHUNK_SIZE
                    and current_chunk
                    and not storage_provider.capabilities.get("supports_random_access")
                ):
                    chunks.append(current_chunk)
                    current_chunk = []
                    current_chunk_size = 0

                # Add item to chunk (even if it makes the chunk > MAX_CHUNK_SIZE,
                # this allows single large files to create their own larger archive).
                current_chunk.append(item)
                current_chunk_size += item_size
            if current_chunk:
                chunks.append(current_chunk)

            for chunk_index, chunk_items in enumerate(chunks):
                if JobManager.is_cancelled(job_id):
                    break

                archive_filename = f"backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{chunk_index}.tar"
                staging_full_path = os.path.join(
                    self.staging_directory, archive_filename
                )

                remaining_to_write = []

                # --- Optimized Deduplication ---
                target_hashes = [
                    item["file_state"].sha256_hash
                    for item in chunk_items
                    if item["file_state"].sha256_hash
                ]
                existing_versions = {}
                SQLITE_VARIABLE_LIMIT = 500
                for i in range(0, len(target_hashes), SQLITE_VARIABLE_LIMIT):
                    sql_chunk = target_hashes[i : i + SQLITE_VARIABLE_LIMIT]
                    chunk_v = (
                        db_session.query(models.FileVersion)
                        .join(models.FilesystemState)
                        .filter(models.FilesystemState.sha256_hash.in_(sql_chunk))
                        .all()
                    )
                    for v in chunk_v:
                        existing_versions[
                            (v.file_state.sha256_hash, v.offset_start, v.offset_end)
                        ] = v

                for item in chunk_items:
                    file_state = item["file_state"]
                    dupe = existing_versions.get(
                        (
                            file_state.sha256_hash,
                            item["offset_start"],
                            item["offset_end"],
                        )
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

                if not remaining_to_write:
                    continue

                if storage_provider.capabilities.get("supports_random_access"):
                    # Random Access: Write files directly
                    import io

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

                        archive_location_id = None
                        if os.path.lexists(file_state.file_path):
                            if os.path.islink(file_state.file_path):
                                target_path = os.readlink(file_state.file_path)
                                with io.BytesIO(
                                    target_path.encode("utf-8")
                                ) as link_stub:
                                    archive_location_id = (
                                        storage_provider.write_file_direct(
                                            media_record.identifier,
                                            internal_name + ".symlink",
                                            link_stub,
                                        )
                                    )
                            else:
                                with RangeFile(
                                    file_state.file_path, start, chunk_size
                                ) as rh:
                                    archive_location_id = (
                                        storage_provider.write_file_direct(
                                            media_record.identifier, internal_name, rh
                                        )
                                    )

                        if archive_location_id:
                            processed_bytes += chunk_size
                            media_record.bytes_used += chunk_size
                            JobManager.update_job(
                                job_id,
                                15.0 + (70.0 * (processed_bytes / safe_divisor)),
                                f"Uploading natively: {os.path.basename(file_state.file_path)}",
                            )

                            db_session.add(
                                models.FileVersion(
                                    filesystem_state_id=file_state.id,
                                    media_id=media_record.id,
                                    file_number=archive_location_id,
                                    is_split=item["is_split"],
                                    split_id=batch_uuid if item["is_split"] else None,
                                    offset_start=item["offset_start"],
                                    offset_end=item["offset_end"],
                                )
                            )
                else:
                    # Sequential Media (Tape): Hybrid Tar Generation
                    has_splits = any(item["is_split"] for item in remaining_to_write)

                    if not has_splits:
                        # PERFORMANCE PATH: Use GNU tar binary for whole files
                        # Prefer gtar on Darwin (macOS ships BSD tar without --null support)
                        tar_binary = None
                        if sys.platform == "darwin":
                            tar_binary = shutil.which("gtar")
                        if tar_binary is None:
                            tar_binary = shutil.which("tar")

                        if tar_binary:
                            # Generate a null-terminated file list to handle special characters safely
                            file_list_path = staging_full_path + ".list"
                            with open(file_list_path, "w") as f_list:
                                for item in remaining_to_write:
                                    # Write absolute path to list
                                    f_list.write(item["file_state"].file_path + "\0")

                            try:
                                # --null must come before -T; --no-recursion and --absolute-names
                                # must come before positional/non-option arguments
                                cmd = [
                                    tar_binary,
                                    "-cf",
                                    staging_full_path,
                                    "--null",
                                    "--no-recursion",
                                    "--absolute-names",
                                    "-T",
                                    file_list_path,
                                ]
                                logger.debug(f"RUNNING BINARY TAR: {' '.join(cmd)}")
                                subprocess.run(cmd, check=True, capture_output=True)

                                # Update progress to 100% for this chunk
                                processed_bytes += sum(
                                    i["offset_end"] - i["offset_start"]
                                    for i in remaining_to_write
                                )
                                JobManager.update_job(
                                    job_id,
                                    15.0 + (70.0 * (processed_bytes / safe_divisor)),
                                    f"Archived chunk {chunk_index+1} via binary tar",
                                )
                            except Exception as e:
                                logger.error(
                                    f"Binary tar failed, falling back to Python: {e}"
                                )
                                has_splits = True  # Trigger fallback
                            finally:
                                if os.path.exists(file_list_path):
                                    os.remove(file_list_path)

                    if has_splits:
                        # COMPATIBILITY PATH: Pure Python for fragments or if tar is missing
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
                                internal_name = self.normalize_path(
                                    file_state.file_path
                                )
                                if item["is_split"]:
                                    internal_name += f".part_{start}_{end}"

                                if os.path.lexists(file_state.file_path):
                                    tar_info = tar_bundle.gettarinfo(
                                        file_state.file_path, arcname=internal_name
                                    )

                                    if os.path.islink(file_state.file_path):
                                        tar_info.type = tarfile.SYMTYPE
                                        tar_info.linkname = os.readlink(
                                            file_state.file_path
                                        )
                                        tar_bundle.addfile(tar_info)
                                    else:
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
                        if os.path.exists(staging_full_path):
                            os.remove(staging_full_path)
                        break

                    with open(staging_full_path, "a") as f:
                        f.flush()
                        os.fsync(f.fileno())

                    JobManager.update_job(
                        job_id,
                        15.0 + (70.0 * (processed_bytes / safe_divisor)),
                        f"Streaming chunk {chunk_index+1}/{len(chunks)} to {media_record.media_type}...",
                    )
                    with open(staging_full_path, "rb") as final_stream:
                        archive_location_id = storage_provider.write_archive(
                            media_record.identifier, final_stream
                        )
                    media_record.bytes_used += os.path.getsize(staging_full_path)

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

                    if os.path.exists(staging_full_path):
                        os.remove(staging_full_path)

            # --- Saturated Media Logic ---
            # If utilized over 98%, mark as full and cede priority
            # First, try to get actual hardware utilization (trust hardware MAM over our byte counts)
            hardware_utilization = None
            if hasattr(storage_provider, "get_utilization"):
                hardware_utilization = storage_provider.get_utilization()

            if hardware_utilization is not None:
                # Handle MagicMock values in tests to prevent formatting errors
                try:
                    utilization_ratio = float(hardware_utilization)
                    logger.info(
                        f"Hardware reported utilization: {utilization_ratio*100:.1f}%"
                    )
                except (TypeError, ValueError):
                    utilization_ratio = (
                        media_record.bytes_used / media_record.capacity
                        if media_record.capacity > 0
                        else 0
                    )
            else:
                utilization_ratio = (
                    media_record.bytes_used / media_record.capacity
                    if media_record.capacity > 0
                    else 0
                )

            if utilization_ratio >= 0.98:
                logger.info(
                    f"MEDIA SATURATED: {media_record.identifier} ({utilization_ratio*100:.1f}%)"
                )
                media_record.status = "full"

                # Automate priority ceding: Move this media to the end of the list
                max_priority = (
                    db_session.query(func.max(models.StorageMedia.priority_index))
                    .filter(models.StorageMedia.id != media_record.id)
                    .scalar()
                    or 0
                )
                media_record.priority_index = max_priority + 1

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
            # Clean up any residual staging files
            for chunk_file in os.listdir(self.staging_directory):
                if chunk_file.startswith("backup_") and chunk_file.endswith(".tar"):
                    try:
                        os.remove(os.path.join(self.staging_directory, chunk_file))
                    except Exception:
                        pass

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
            if cart_item.file_state.is_deleted:
                continue
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

                    is_tar = self._test_is_tar_logic(provider, media_record, archive_id)

                    if not is_tar:
                        # Format Negotiation: Direct file recovery
                        for v in target_versions:
                            if JobManager.is_cancelled(job_id):
                                break
                            final_path = self._sanitize_recovery_path(
                                destination_root, v.file_state.file_path
                            )
                            os.makedirs(os.path.dirname(final_path), exist_ok=True)

                            # Handle symlink stubs
                            if str(archive_id).endswith(".symlink"):
                                target_link_path = bitstream.read().decode("utf-8")
                                if os.path.lexists(final_path):
                                    os.remove(final_path)
                                os.symlink(target_link_path, final_path)
                            else:
                                mode = "r+b" if os.path.exists(final_path) else "wb"
                                with open(final_path, mode) as dst:
                                    if v.is_split:
                                        if mode == "wb":
                                            dst.truncate(v.file_state.size)
                                        dst.seek(v.offset_start)
                                    shutil.copyfileobj(bitstream, dst)

                                # Attempt to restore basic metadata (mtime) from index
                                try:
                                    os.utime(
                                        final_path,
                                        (v.file_state.mtime, v.file_state.mtime),
                                    )
                                except Exception:
                                    pass

                            processed_bytes += v.offset_end - v.offset_start
                            JobManager.update_job(
                                job_id,
                                min(
                                    99.0,
                                    5.0
                                    + (
                                        90.0
                                        * (processed_bytes / max(v.file_state.size, 1))
                                    ),
                                ),
                                f"Restoring natively: {os.path.basename(v.file_state.file_path)}",
                            )
                        continue

                    tar_mode = (
                        "r|*"
                        if media_record.media_type
                        in ["tape", "lto_tape", "cloud", "s3_compat"]
                        else "r:*"
                    )

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

    def _test_is_tar_logic(self, provider, media_record, archive_id: str) -> bool:
        """Internal logic to determine if a location_id refers to a tarball vs a native file."""
        # 1. If provider doesn't support random access (Tape), it's ALWAYS a tar stream.
        if not provider.capabilities.get("supports_random_access"):
            return True

        # 2. Explicit extensions or prefixes
        if str(archive_id).endswith(".tar") or "archives/" in str(archive_id):
            return True

        # 3. Tape file numbers (if they happen to be passed here for cloud, which is rare)
        if str(archive_id).isdigit() and media_record.media_type in [
            "tape",
            "lto_tape",
        ]:
            return True

        # 4. Otherwise, if it has random access (Cloud/HDD) and isn't explicitly an archive,
        # it's a native file.
        return False


archiver_manager = ArchiverService()
