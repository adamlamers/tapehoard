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
from sqlalchemy import func, not_, text
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.orm.exc import StaleDataError

from app.db import models
from app.providers.cloud import CloudStorageProvider
from app.providers.dropbox_provider import DropboxProvider
from app.providers.google_drive import GoogleDriveProvider
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
            GoogleDriveProvider.provider_id: GoogleDriveProvider,
            DropboxProvider.provider_id: DropboxProvider,
            # Backwards compatibility for legacy DB records
            "tape": LTOProvider,
            "hdd": OfflineHDDProvider,
            "cloud": CloudStorageProvider,
            "s3": CloudStorageProvider,
        }

        if os.environ.get("TAPEHOARD_TEST_MODE") == "true":
            from app.providers.mock import MockLTOProvider

            # In test mode, replace LTOProvider with MockLTOProvider
            provider_map[LTOProvider.provider_id] = (
                MockLTOProvider  # ty: ignore[invalid-assignment]
            )
            # Also keep mock_lto mapping for backward compatibility
            provider_map[MockLTOProvider.provider_id] = (
                MockLTOProvider  # ty: ignore[invalid-assignment]
            )

        provider_cls = provider_map.get(media_record.media_type)
        if not provider_cls:
            return None

        # Build provider config from extra_config (legacy) and first-class columns
        provider_config: Dict[str, Any] = {}
        if media_record.extra_config:
            try:
                provider_config = json.loads(media_record.extra_config)
            except json.JSONDecodeError:
                logger.error(
                    f"Failed to decode config for media {media_record.identifier}"
                )

        # Add first-class columns to config based on media type
        if media_record.media_type == "lto_tape":
            if media_record.compression is not None:
                provider_config.setdefault("compression", media_record.compression)
            if media_record.encryption_key_id:
                provider_config.setdefault(
                    "encryption_key", media_record.encryption_key_id
                )
            if media_record.generation:
                provider_config.setdefault("generation", media_record.generation)
        elif media_record.media_type == "local_hdd":
            if media_record.mount_path:
                provider_config.setdefault("mount_path", media_record.mount_path)
            if media_record.device_uuid:
                provider_config.setdefault("device_uuid", media_record.device_uuid)
        elif media_record.media_type == "s3_compat":
            if media_record.endpoint_url:
                provider_config.setdefault("endpoint_url", media_record.endpoint_url)
            if media_record.region:
                provider_config.setdefault("region", media_record.region)
            if media_record.bucket_name:
                provider_config.setdefault("bucket_name", media_record.bucket_name)
            if media_record.access_key_id:
                provider_config.setdefault("access_key", media_record.access_key_id)
            if media_record.secret_access_key_name:
                provider_config.setdefault(
                    "secret_access_key_name", media_record.secret_access_key_name
                )
            if media_record.encryption_secret_name:
                provider_config.setdefault(
                    "encryption_secret_name",
                    media_record.encryption_secret_name,
                )
            provider_config.setdefault(
                "obfuscate_filenames", media_record.obfuscate_filenames
            )
        # google_drive and dropbox store all config in extra_config — already loaded above

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
                models.FilesystemState.is_deleted.is_(False),
                (coverage_subquery.c.covered_bytes.is_(None))
                | (coverage_subquery.c.covered_bytes < models.FilesystemState.size),
            )
            .yield_per(1000)
        )

    def _get_redundancy_target(self, db_session: Session) -> int:
        """Reads the redundancy_target system setting; defaults to 1."""
        setting = (
            db_session.query(models.SystemSetting)
            .filter(models.SystemSetting.key == "redundancy_target")
            .first()
        )
        if setting:
            try:
                val = int(setting.value)
                if val >= 1:
                    return val
            except (ValueError, TypeError):
                pass
        return 1

    def _get_redundant_candidates(
        self, db_session: Session, media_id: int, redundancy_target: int
    ):
        """Files that have ≥1 complete copy but fewer than redundancy_target copies.

        These files are returned without a global-covered-bytes offset; each redundant
        copy is written from byte 0.  Only files that fit entirely on this media are
        included (no splits for redundant copies).
        """
        coverage_on_this_media = (
            db_session.query(models.FileMediaCoverage.file_id)
            .filter(models.FileMediaCoverage.media_id == media_id)
            .scalar_subquery()
        )

        return (
            db_session.query(models.FilesystemState)
            .filter(
                not_(models.FilesystemState.is_ignored),
                models.FilesystemState.is_deleted.is_(False),
                models.FilesystemState.redundancy_count >= 1,
                models.FilesystemState.redundancy_count < redundancy_target,
                ~models.FilesystemState.id.in_(coverage_on_this_media),
            )
            .yield_per(1000)
        )

    def _record_coverage(
        self, db_session: Session, items: List[Dict[str, Any]], media_id: int
    ) -> None:
        """Insert file_media_coverage rows for non-split complete copies."""
        for item in items:
            if (
                item["offset_start"] == 0
                and item["offset_end"] == item["file_state"].size
            ):
                db_session.execute(
                    text(
                        "INSERT OR IGNORE INTO file_media_coverage (file_id, media_id)"
                        " VALUES (:file_id, :media_id)"
                    ),
                    {"file_id": item["file_state"].id, "media_id": media_id},
                )

    def assemble_backup_batch(
        self,
        db_session: Session,
        media_id: int,
        max_batch_size: Optional[int] = None,
        redundancy_target: int = 1,
    ) -> List[Dict[str, Any]]:
        """Selects a workload batch that fits within the available media capacity."""
        media_record = db_session.get(models.StorageMedia, media_id)
        if not media_record:
            return []

        remaining_capacity = media_record.capacity - media_record.bytes_used
        if max_batch_size:
            remaining_capacity = min(remaining_capacity, max_batch_size)

        logger.debug(
            f"assemble_backup_batch: media={media_record.identifier} "
            f"capacity={media_record.capacity} bytes_used={media_record.bytes_used} "
            f"remaining={remaining_capacity} redundancy_target={redundancy_target}"
        )

        backup_workload = []
        accumulated_size = 0
        MINIMUM_FRAGMENT_SIZE = 100 * 1024 * 1024  # 100MB

        # Track file IDs already added to avoid duplicates between phases
        queued_ids: set = set()

        # --- Phase 1: First-time backup ---
        # Uses global covered-bytes offset so large files can be split across media.
        # Files already with any version OR coverage on this media are skipped.
        on_this_media_ids: set = set(
            row[0]
            for row in db_session.query(models.FileVersion.filesystem_state_id)
            .filter(models.FileVersion.media_id == media_id)
            .distinct()
        )
        on_this_media_ids.update(
            row[0]
            for row in db_session.query(models.FileMediaCoverage.file_id).filter(
                models.FileMediaCoverage.media_id == media_id
            )
        )

        unbacked_files = self.get_unbacked_files(db_session)

        for file_state, covered_bytes in unbacked_files:
            if accumulated_size >= remaining_capacity:
                break
            if file_state.id in on_this_media_ids:
                continue
            if file_state.redundancy_count >= redundancy_target:
                continue

            remaining_file_bytes = file_state.size - covered_bytes

            if file_state.size == 0:
                # Guard: if the file has grown on disk since the scan, skip it so a
                # subsequent rescan can update the DB size before we archive it.
                try:
                    actual_size = os.path.getsize(file_state.file_path)
                except OSError:
                    actual_size = 0
                if actual_size > 0:
                    logger.info(
                        f"Skipping {file_state.file_path}: DB size=0 but disk size="
                        f"{actual_size} — re-archive after next scan"
                    )
                    continue

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
                    queued_ids.add(file_state.id)
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
                queued_ids.add(file_state.id)
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
                queued_ids.add(file_state.id)
                break
            else:
                # File is larger than remaining space but smaller than total media capacity.
                # Skip it for this media to avoid unnecessary fragmentation.
                continue

        logger.debug(
            f"assemble_backup_batch: Phase 1 complete — {len(backup_workload)} files, "
            f"accumulated={accumulated_size} of {remaining_capacity} bytes"
        )

        # --- Phase 2: Redundant copies ---
        # Files with ≥1 complete copy that still need more.  Each redundant copy is
        # written in full (offset 0 → size); no splitting allowed so that every
        # redundant copy is independently restorable.
        # is_redundant_copy=True skips deduplication so the file is physically written
        # to this media rather than pointing back to an existing copy elsewhere.
        if redundancy_target > 1 and accumulated_size < remaining_capacity:
            p2_candidates = list(
                self._get_redundant_candidates(db_session, media_id, redundancy_target)
            )
            logger.debug(
                f"assemble_backup_batch: Phase 2 — {len(p2_candidates)} redundant "
                f"candidates for media={media_record.identifier} target={redundancy_target} "
                f"remaining_space={remaining_capacity - accumulated_size}"
            )
            for file_state in p2_candidates:
                if accumulated_size >= remaining_capacity:
                    break
                if file_state.id in queued_ids:
                    continue

                available_space = remaining_capacity - accumulated_size
                if file_state.size <= available_space:
                    backup_workload.append(
                        {
                            "file_state": file_state,
                            "offset_start": 0,
                            "offset_end": file_state.size,
                            "is_split": False,
                            "is_redundant_copy": True,
                        }
                    )
                    accumulated_size += file_state.size
                    queued_ids.add(file_state.id)
                # If file doesn't fit, skip — can't create an independently
                # restorable redundant copy on this media right now.
        elif redundancy_target > 1:
            logger.debug(
                f"assemble_backup_batch: Phase 2 skipped — media at capacity "
                f"(accumulated={accumulated_size} >= remaining={remaining_capacity})"
            )

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

    def _get_tape_write_strategy(self, db_session: Session) -> str:
        """Reads the user-configured tape write strategy. Defaults to staging."""
        setting = (
            db_session.query(models.SystemSetting)
            .filter(models.SystemSetting.key == "tape_write_strategy")
            .first()
        )
        if setting and setting.value in ("stage", "stream"):
            return setting.value
        return "stage"

    def _filter_unstable_files(
        self,
        items: List[Dict[str, Any]],
        job_start_time: datetime,
        job_id: int,
    ) -> tuple[List[Dict[str, Any]], set]:
        """Skips files whose mtime is after the backup job began.

        This prevents archiving partially-modified files.  A log entry is
        emitted for every skipped file.

        Returns a tuple of (stable_items, skipped_file_ids).
        """
        stable_items: List[Dict[str, Any]] = []
        skipped_ids: set = set()
        for item in items:
            file_state = item["file_state"]
            try:
                actual_mtime = os.stat(file_state.file_path).st_mtime
            except (OSError, FileNotFoundError):
                # File disappeared between scan and backup; skip it
                JobManager.add_job_log(
                    job_id,
                    f"Skipped (missing): {file_state.file_path}",
                )
                skipped_ids.add(file_state.id)
                continue

            # Compare with a small epsilon to avoid false positives from
            # sub-second resolution differences.
            if actual_mtime > job_start_time.timestamp() + 0.001:
                JobManager.add_job_log(
                    job_id,
                    (
                        f"Skipped (actively modified after job start): "
                        f"{file_state.file_path}"
                    ),
                )
                skipped_ids.add(file_state.id)
                continue

            stable_items.append(item)

        return stable_items, skipped_ids

    def _build_tar(self, items, stream, job_id, safe_divisor, processed_bytes):
        """Builds a tar archive into the provided writable stream.
        Returns the updated processed_bytes count."""
        tar_bundle = tarfile.open(fileobj=stream, mode="w")
        # Match LTO optimal block size so each write() is a full tape block
        tar_bundle.copybufsize = 256 * 1024  # ty: ignore[unresolved-attribute]

        members_added = 0
        for item in items:
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
                tar_info = tar_bundle.gettarinfo(
                    file_state.file_path, arcname=internal_name
                )

                if os.path.islink(file_state.file_path):
                    tar_info.type = tarfile.SYMTYPE
                    tar_info.linkname = os.readlink(file_state.file_path)
                    tar_bundle.addfile(tar_info)
                else:
                    tar_info.type = tarfile.REGTYPE
                    tar_info.linkname = ""
                    tar_info.size = chunk_size

                    with RangeFile(file_state.file_path, start, chunk_size) as rh:
                        tar_bundle.addfile(tar_info, rh)

                members_added += 1
            else:
                logger.warning(f"File missing during backup: {file_state.file_path}")

            processed_bytes += chunk_size
            JobManager.update_job(
                job_id,
                15.0 + (70.0 * (processed_bytes / safe_divisor)),
                f"Archiving: {os.path.basename(file_state.file_path)}",
            )

        tar_bundle.close()

        if members_added == 0:
            logger.warning(
                f"Tar archive has 0 members ({len(items)} items requested). "
                f"All files may have been deleted between scan and backup."
            )

        # Ensure all buffered data is pushed from Python/io through to the OS
        # before the caller proceeds to finalize (e.g., write file marks).
        try:
            stream.flush()
            if hasattr(stream, "fileno"):
                os.fsync(stream.fileno())
        except (OSError, ValueError):
            # fsync may not be supported on all streams (e.g., pipes, tape on some OS)
            pass

        return processed_bytes

    def _log_compression_ratio(
        self,
        job_id: int,
        chunk_num: int,
        uncompressed_size: int,
        hw_before: Optional[float],
        hw_after: Optional[float],
        media_capacity: int,
    ) -> int:
        """Calculates and logs compression ratio. Returns actual bytes consumed."""
        if hw_before is not None and hw_after is not None and media_capacity > 0:
            actual_bytes = int((hw_after - hw_before) * media_capacity)
            if actual_bytes > 0:
                ratio = uncompressed_size / actual_bytes
                JobManager.add_job_log(
                    job_id,
                    f"Chunk {chunk_num}: {ratio:.2f}:1 compression "
                    f"({uncompressed_size / (1024**3):.2f} GB uncompressed → "
                    f"{actual_bytes / (1024**3):.2f} GB on tape)",
                )
                return actual_bytes
        return uncompressed_size

    def _update_bytes_used_from_hardware(
        self,
        media_record: models.StorageMedia,
        storage_provider: Any,
    ) -> bool:
        """Syncs bytes_used to hardware-reported utilization when available.

        Returns True if bytes_used was updated from hardware, False if the
        provider either lacks get_utilization, returned None, or raised.
        """
        from unittest.mock import Mock

        if hasattr(storage_provider, "get_utilization"):
            try:
                hw_util = storage_provider.get_utilization()
            except Exception:
                return False
            # Skip mock objects (tests) and invalid values
            if hw_util is not None and not isinstance(hw_util, Mock):
                try:
                    media_record.bytes_used = int(
                        float(hw_util) * media_record.capacity
                    )
                    return True
                except (TypeError, ValueError):
                    pass
        return False

    def run_backup(self, db_session: Session, media_id: int, job_id: int):
        """Orchestrates the archival of a data batch to a storage provider."""
        media_record = db_session.get(models.StorageMedia, media_id)
        if not media_record:
            JobManager.fail_job(job_id, "Media record not found.")
            return

        # Capture identifiers early to avoid StaleDataError/ObjectDeletedError
        # if the ORM object becomes stale during the long-running backup
        media_id_for_log = media_record.id
        media_identifier_for_log = media_record.identifier

        JobManager.start_job(job_id)
        job_start_time = datetime.now(timezone.utc)
        JobManager.update_job(
            job_id, 5.0, f"Calculating backup set for {media_record.identifier}..."
        )
        JobManager.add_job_log(job_id, f"Starting backup to {media_record.identifier}")

        redundancy_target = self._get_redundancy_target(db_session)

        from app.core.utils import set_process_priority

        set_process_priority("background")

        # --- Tar Chunking Logic ---
        # With hardware compression, actual tape usage is ~50-70% of uncompressed.
        # Use capacity / 50 as chunk target so we get larger, more efficient tars
        # while still maintaining reasonable restore granularity.
        MAX_CHUNK_SIZE = media_record.capacity // 50
        if MAX_CHUNK_SIZE < 100 * 1024 * 1024:  # Minimum 100MB chunk
            MAX_CHUNK_SIZE = 100 * 1024 * 1024

        # Sanity check: MAX_CHUNK_SIZE should be at least 1MB.
        # If capacity is so small that MAX_CHUNK_SIZE < 1MB, the unit is probably
        # wrong (GB stored as bytes) which would create a chunk per file.
        if MAX_CHUNK_SIZE < 1024 * 1024:
            logger.warning(
                f"Media {media_record.identifier} capacity ({media_record.capacity}) "
                f"produces MAX_CHUNK_SIZE of {MAX_CHUNK_SIZE} bytes. "
                f"This looks like capacity is stored in GB instead of bytes. "
                f"Aborting backup to avoid creating thousands of tiny archives."
            )
            JobManager.fail_job(
                job_id,
                f"Media capacity ({media_record.capacity}) produces chunks of "
                f"{MAX_CHUNK_SIZE} bytes — expected bytes, got GB? "
                f"Re-register media with correct capacity.",
            )
            return

        JobManager.add_job_log(
            job_id,
            f"Chunk target: {MAX_CHUNK_SIZE / (1024 * 1024):.0f}MB "
            f"(capacity {media_record.capacity / (1024 ** 3):.1f}GiB / 50)",
        )

        storage_provider = self._get_storage_provider(media_record)
        if not storage_provider:
            JobManager.fail_job(
                job_id, f"Unsupported hardware: {media_record.media_type}"
            )
            return

        tape_strategy = self._get_tape_write_strategy(db_session)
        use_streaming = (
            tape_strategy == "stream"
            and hasattr(storage_provider, "open_stream")
            and hasattr(storage_provider, "finalize_stream")
        )

        try:
            if storage_provider.identify_media() != media_record.identifier:
                JobManager.fail_job(job_id, "Hardware mismatch.")
                return

            if not storage_provider.prepare_for_write(media_record.identifier):
                JobManager.fail_job(job_id, "Hardware refused write initialization.")
                return

            processed_bytes = 0
            batch_iteration = 0
            # Track files skipped in this job so we don't retry them in
            # subsequent batches of the same job.
            skipped_file_ids: set = set()

            # Keep filling the tape in batches until it's full or no files remain
            while True:
                batch_iteration += 1

                # Sync bytes_used from hardware so remaining_capacity is accurate
                self._update_bytes_used_from_hardware(media_record, storage_provider)

                workload_batch = self.assemble_backup_batch(
                    db_session, media_id, redundancy_target=redundancy_target
                )
                if not workload_batch:
                    db_session.refresh(media_record)
                    remaining = media_record.capacity - media_record.bytes_used
                    reason = (
                        "media is full"
                        if remaining <= 0
                        else (
                            f"all files at or above redundancy target ({redundancy_target}), "
                            f"already covered on this media, or too large for remaining "
                            f"{remaining:,} bytes"
                        )
                    )
                    JobManager.add_job_log(
                        job_id,
                        f"Batch {batch_iteration}: No more files require backup — {reason}",
                    )
                    break

                JobManager.add_job_log(
                    job_id,
                    f"Batch {batch_iteration}: {len(workload_batch)} files queued for backup",
                )

                total_payload_bytes = sum(
                    item["offset_end"] - item["offset_start"] for item in workload_batch
                )
                safe_divisor = max(total_payload_bytes, 1)

                batch_uuid = str(uuid.uuid4())

                # Split workload into chunks for packaging
                chunks = []
                current_chunk = []
                current_chunk_size = 0
                for item in workload_batch:
                    item_size = item["offset_end"] - item["offset_start"]

                    if (
                        current_chunk_size + item_size > MAX_CHUNK_SIZE
                        and current_chunk
                        and not storage_provider.capabilities.get(
                            "supports_random_access"
                        )
                    ):
                        chunks.append(current_chunk)
                        current_chunk = []
                        current_chunk_size = 0

                    current_chunk.append(item)
                    current_chunk_size += item_size
                if current_chunk:
                    chunks.append(current_chunk)

                # --- Staging Space Validation (only for stage mode) ---
                if not use_streaming and not storage_provider.capabilities.get(
                    "supports_random_access"
                ):
                    largest_chunk_size = max(
                        sum(i["offset_end"] - i["offset_start"] for i in chunk)
                        for chunk in chunks
                    )
                    try:
                        usage = shutil.disk_usage(self.staging_directory)
                        required = int(largest_chunk_size * 1.1)
                        if usage.free < required:
                            free_gb = usage.free / (1024**3)
                            req_gb = required / (1024**3)
                            JobManager.fail_job(
                                job_id,
                                f"Staging area at {self.staging_directory} has only {free_gb:.1f} GB free, "
                                f"but the largest archive chunk requires {req_gb:.1f} GB. "
                                f"Free up space or reduce the backup set.",
                            )
                            return
                    except OSError as e:
                        logger.warning(f"Could not check staging disk usage: {e}")

                JobManager.add_job_log(
                    job_id,
                    f"Batch {batch_iteration}: Packed into {len(chunks)} archive(s) "
                    f"(strategy: {'stream' if use_streaming else 'stage'})",
                )

                # Track whether any actual progress was made in this batch.
                # If all files are skipped (missing/unstable) and none are
                # deduplicated, we should not keep looping on the same files.
                batch_versions_created = 0

                for chunk_index, chunk_items in enumerate(chunks):
                    if JobManager.is_cancelled(job_id):
                        break

                    chunk_num = chunk_index + 1
                    JobManager.add_job_log(
                        job_id,
                        f"Processing archive {chunk_num}/{len(chunks)} ({len(chunk_items)} files)",
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
                        # Skip dedup for redundant copies: a pointer to another
                        # media is not a physically independent redundant copy.
                        dupe = None
                        if not item.get("is_redundant_copy"):
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
                            batch_versions_created += 1
                        else:
                            remaining_to_write.append(item)

                    # Exclude files already skipped in an earlier batch of this job
                    remaining_to_write = [
                        item
                        for item in remaining_to_write
                        if item["file_state"].id not in skipped_file_ids
                    ]

                    # Filter out files modified after the job started
                    remaining_to_write, newly_skipped = self._filter_unstable_files(
                        remaining_to_write, job_start_time, job_id
                    )
                    skipped_file_ids.update(newly_skipped)

                    if not remaining_to_write:
                        try:
                            db_session.commit()
                            JobManager.add_job_log(
                                job_id,
                                f"Checkpoint: chunk {chunk_num} deduplicated",
                            )
                        except StaleDataError:
                            db_session.rollback()
                            logger.warning(
                                f"Checkpoint commit failed for deduplicated chunk {chunk_num}"
                            )
                        continue

                    # Capture hardware utilization before writing
                    hw_util_before = None
                    if hasattr(storage_provider, "get_utilization"):
                        try:
                            hw_util_before = storage_provider.get_utilization()
                        except Exception:
                            pass

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
                                                media_record.identifier,
                                                internal_name,
                                                rh,
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
                                        split_id=batch_uuid
                                        if item["is_split"]
                                        else None,
                                        offset_start=item["offset_start"],
                                        offset_end=item["offset_end"],
                                    )
                                )
                                batch_versions_created += 1

                        self._record_coverage(
                            db_session, remaining_to_write, media_record.id
                        )
                        try:
                            db_session.commit()
                            JobManager.add_job_log(
                                job_id,
                                f"Checkpoint: chunk {chunk_num} committed",
                            )
                        except StaleDataError:
                            db_session.rollback()
                            logger.warning(
                                f"Checkpoint commit failed for chunk {chunk_num}"
                            )

                    elif use_streaming:
                        # --- Direct Streaming Path ---
                        # Build tar directly into the tape device without staging.
                        tape_stream = storage_provider.open_stream()
                        try:
                            processed_bytes = self._build_tar(
                                remaining_to_write,
                                tape_stream,
                                job_id,
                                safe_divisor,
                                processed_bytes,
                            )
                        finally:
                            # Close the stream before finalize so the tape driver
                            # can finish flushing its internal buffer without an
                            # open writer blocking subsequent mt commands.
                            tape_stream.close()

                        # Stream is closed; now write the file mark.
                        try:
                            archive_location_id = storage_provider.finalize_stream()
                        except subprocess.CalledProcessError as e:
                            stderr = getattr(e, "stderr", "")
                            JobManager.fail_job(
                                job_id,
                                f"Tape command failed during finalize: {e} stderr={stderr!r}",
                            )
                            return

                        uncompressed_size = sum(
                            i["offset_end"] - i["offset_start"]
                            for i in remaining_to_write
                        )

                        # Capture hardware utilization after writing
                        hw_util_after = None
                        if hasattr(storage_provider, "get_utilization"):
                            try:
                                hw_util_after = storage_provider.get_utilization()
                            except Exception:
                                pass

                        # Log compression ratio and sync bytes_used to hardware
                        self._log_compression_ratio(
                            job_id,
                            chunk_num,
                            uncompressed_size,
                            hw_util_before,
                            hw_util_after,
                            media_record.capacity,
                        )
                        hw_updated = self._update_bytes_used_from_hardware(
                            media_record, storage_provider
                        )
                        if not hw_updated:
                            # Hardware didn't report; fall back to uncompressed size
                            media_record.bytes_used += uncompressed_size

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
                            batch_versions_created += 1

                        self._record_coverage(
                            db_session, remaining_to_write, media_record.id
                        )
                        try:
                            db_session.commit()
                            JobManager.add_job_log(
                                job_id,
                                f"Checkpoint: archive {chunk_num} committed (tape file #{archive_location_id})",
                            )
                        except StaleDataError:
                            db_session.rollback()
                            logger.warning(
                                f"Checkpoint commit failed for archive {chunk_num}"
                            )

                    else:
                        # --- Staging Path ---
                        archive_filename = f"backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{chunk_index}.tar"
                        staging_full_path = os.path.join(
                            self.staging_directory, archive_filename
                        )

                        has_splits = any(
                            item["is_split"] for item in remaining_to_write
                        )

                        if not has_splits:
                            tar_binary = None
                            if sys.platform == "darwin":
                                tar_binary = shutil.which("gtar")
                            if tar_binary is None:
                                tar_binary = shutil.which("tar")

                            if tar_binary:
                                file_list_path = staging_full_path + ".list"
                                with open(file_list_path, "w") as f_list:
                                    for item in remaining_to_write:
                                        f_list.write(
                                            item["file_state"].file_path + "\0"
                                        )

                                try:
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

                                    processed_bytes += sum(
                                        i["offset_end"] - i["offset_start"]
                                        for i in remaining_to_write
                                    )
                                    JobManager.update_job(
                                        job_id,
                                        15.0
                                        + (70.0 * (processed_bytes / safe_divisor)),
                                        f"Archived chunk {chunk_index + 1} via binary tar",
                                    )
                                except Exception as e:
                                    logger.error(
                                        f"Binary tar failed, falling back to Python: {e}"
                                    )
                                    has_splits = True
                                finally:
                                    if os.path.exists(file_list_path):
                                        os.remove(file_list_path)

                        if has_splits:
                            with open(staging_full_path, "wb") as f:
                                processed_bytes = self._build_tar(
                                    remaining_to_write,
                                    f,
                                    job_id,
                                    safe_divisor,
                                    processed_bytes,
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
                            f"Streaming chunk {chunk_index + 1}/{len(chunks)} to {media_record.media_type}...",
                        )
                        with open(staging_full_path, "rb") as final_stream:
                            try:
                                archive_location_id = storage_provider.write_archive(
                                    media_record.identifier, final_stream
                                )
                            except subprocess.CalledProcessError as e:
                                stderr = getattr(e, "stderr", "")
                                JobManager.fail_job(
                                    job_id,
                                    f"Tape command failed during write: {e} stderr={stderr!r}",
                                )
                                return

                        uncompressed_size = os.path.getsize(staging_full_path)

                        # Capture hardware utilization after writing
                        hw_util_after = None
                        if hasattr(storage_provider, "get_utilization"):
                            try:
                                hw_util_after = storage_provider.get_utilization()
                            except Exception:
                                pass

                        # Log compression ratio and sync bytes_used to hardware
                        self._log_compression_ratio(
                            job_id,
                            chunk_num,
                            uncompressed_size,
                            hw_util_before,
                            hw_util_after,
                            media_record.capacity,
                        )
                        hw_updated = self._update_bytes_used_from_hardware(
                            media_record, storage_provider
                        )
                        if not hw_updated:
                            # Hardware didn't report; fall back to uncompressed size
                            media_record.bytes_used += uncompressed_size

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
                            batch_versions_created += 1

                        if os.path.exists(staging_full_path):
                            os.remove(staging_full_path)

                        self._record_coverage(
                            db_session, remaining_to_write, media_record.id
                        )
                        try:
                            db_session.commit()
                            JobManager.add_job_log(
                                job_id,
                                f"Checkpoint: archive {chunk_num} committed (tape file #{archive_location_id})",
                            )
                        except StaleDataError:
                            db_session.rollback()
                            logger.warning(
                                f"Checkpoint commit failed for archive {chunk_num}"
                            )

                # --- Check saturation / progress after each batch ---
                if JobManager.is_cancelled(job_id):
                    break

                # If no files were written or deduplicated this batch, all
                # remaining files were skipped (missing/unstable). Break to
                # avoid an infinite loop on the same skipped files.
                if batch_versions_created == 0:
                    JobManager.add_job_log(
                        job_id,
                        f"Batch {batch_iteration}: No files could be archived "
                        f"(all skipped or missing). Ending backup.",
                    )
                    break

                self._update_bytes_used_from_hardware(media_record, storage_provider)
                utilization_ratio = (
                    media_record.bytes_used / media_record.capacity
                    if media_record.capacity > 0
                    else 0
                )
                logger.info(
                    f"Hardware reported utilization: {utilization_ratio * 100:.1f}%"
                )

                if utilization_ratio >= 0.98 and media_record.status == "active":
                    logger.info(
                        f"MEDIA SATURATED: {media_record.identifier} ({utilization_ratio * 100:.1f}%)"
                    )
                    media_record.status = "full"

                    JobManager.add_job_log(
                        job_id,
                        f"Media {media_record.identifier} marked as full",
                    )

                    max_priority = (
                        db_session.query(func.max(models.StorageMedia.priority_index))
                        .filter(models.StorageMedia.id != media_record.id)
                        .scalar()
                        or 0
                    )
                    media_record.priority_index = max_priority + 1

                    try:
                        db_session.commit()
                    except StaleDataError:
                        db_session.rollback()
                    break

            # --- Final commit + completion ---
            self._update_bytes_used_from_hardware(media_record, storage_provider)
            utilization_ratio = (
                media_record.bytes_used / media_record.capacity
                if media_record.capacity > 0
                else 0
            )

            try:
                db_session.commit()
            except StaleDataError:
                db_session.rollback()
                logger.warning(
                    f"Media record {media_id_for_log} was modified or deleted by another process; skipping final commit"
                )

            if JobManager.is_cancelled(job_id):
                JobManager.add_job_log(
                    job_id,
                    f"Backup cancelled. Utilization: {utilization_ratio * 100:.1f}%",
                )
            else:
                JobManager.add_job_log(
                    job_id,
                    f"Backup complete. Utilization: {utilization_ratio * 100:.1f}%",
                )
                JobManager.complete_job(job_id)
                from app.services.notifications import notification_manager

                notification_manager.notify(
                    "Archival Complete",
                    f"{media_identifier_for_log} synchronized.",
                    "success",
                )

        except Exception as e:
            logger.exception(f"Archival failed: {e}")
            JobManager.fail_job(job_id, str(e))
        finally:
            set_process_priority("normal")
            for chunk_file in os.listdir(self.staging_directory):
                if chunk_file.startswith("backup_") and chunk_file.endswith(".tar"):
                    try:
                        os.remove(os.path.join(self.staging_directory, chunk_file))
                    except Exception as e:
                        logger.debug(f"Failed to remove staging file {chunk_file}: {e}")

    def run_restore(self, db_session: Session, destination_root: str, job_id: int):
        """Orchestrates the retrieval and reassembly of data from storage providers."""
        JobManager.start_job(job_id)
        JobManager.update_job(job_id, 2.0, "Building recovery manifest...")
        JobManager.add_job_log(job_id, "Starting restore")

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
            JobManager.add_job_log(job_id, "Restore queue is empty, nothing to do")
            JobManager.complete_job(job_id)
            return

        JobManager.add_job_log(job_id, f"{len(active_cart)} items in restore queue")

        os.makedirs(destination_root, exist_ok=True)

        media_workload: Dict[int, Dict[str, List[models.FileVersion]]] = {}
        skipped_acknowledged = 0
        for cart_item in active_cart:
            if cart_item.file_state.is_deleted:
                continue
            if cart_item.file_state.missing_acknowledged_at is not None:
                skipped_acknowledged += 1
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

        if skipped_acknowledged:
            JobManager.add_job_log(
                job_id,
                f"Skipped {skipped_acknowledged} item(s) with acknowledged loss (missing_acknowledged_at set)",
            )

        processed_bytes = 0
        try:
            for media_id, archive_groups in media_workload.items():
                if JobManager.is_cancelled(job_id):
                    break
                media_record = db_session.get(models.StorageMedia, media_id)
                if not media_record:
                    continue
                JobManager.add_job_log(
                    job_id,
                    f"Reading from {media_record.identifier} ({len(archive_groups)} archive(s))",
                )
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

                # Sort archive IDs numerically when possible (tape file numbers),
                # falling back to string sort for non-numeric IDs (HDD paths, cloud keys).
                # This ensures tape restores read linearly instead of seeking
                # back and forth due to string ordering ("1", "10", "11", "2"...).
                def _archive_sort_key(archive_id: str):
                    try:
                        return (0, int(archive_id))
                    except ValueError:
                        return (1, archive_id)

                for archive_id in sorted(archive_groups.keys(), key=_archive_sort_key):
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
                                except Exception as e:
                                    logger.debug(
                                        f"Failed to restore mtime for {final_path}: {e}"
                                    )

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

                    # For tape, we open the device directly (not via dd pipe) so we can
                    # seek through the tar efficiently and stop early once all files are found.
                    # Use buffered read mode for better performance.
                    tar_mode = "r:*"

                    normalized_map = {}
                    for v in target_versions:
                        name = self.normalize_path(v.file_state.file_path)
                        if v.is_split:
                            name += f".part_{v.offset_start}_{v.offset_end}"
                        normalized_map[name] = v

                    # Track which files we still need to find
                    remaining_files = set(normalized_map.keys())
                    found_count = 0

                    try:
                        with tarfile.open(
                            fileobj=bitstream, mode=tar_mode
                        ) as tar_bundle:
                            for member in tar_bundle:
                                if JobManager.is_cancelled(job_id):
                                    break

                                # Optimization: stop early if we've found all target files
                                if not remaining_files:
                                    logger.debug(
                                        f"All {found_count} target files found in archive {archive_id}, "
                                        f"stopping tar iteration early"
                                    )
                                    break

                                clean_name = self.normalize_path(member.name)
                                if clean_name not in normalized_map:
                                    continue

                                remaining_files.discard(clean_name)
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
                                            except Exception as e:
                                                logger.debug(
                                                    f"Failed to restore ownership for {final_path}: {e}"
                                                )
                                        except Exception as meta_err:
                                            logger.debug(
                                                f"Failed to apply metadata to {final_path}: {meta_err}"
                                            )

                                        processed_bytes += v.offset_end - v.offset_start
                                elif member.issym() or member.islnk():
                                    # Handle symlinks - extract manually to control destination
                                    link_target = member.linkname
                                    if os.path.lexists(final_path):
                                        os.remove(final_path)
                                    os.symlink(link_target, final_path)
                                elif member.isdir():
                                    # Create directory with proper permissions
                                    os.makedirs(final_path, exist_ok=True)
                                    try:
                                        os.chmod(final_path, member.mode)
                                        os.utime(
                                            final_path, (member.mtime, member.mtime)
                                        )
                                    except Exception as e:
                                        logger.debug(
                                            f"Failed to apply metadata to directory {final_path}: {e}"
                                        )

                        if found_count == 0:
                            raise FileNotFoundError(f"Archive {archive_id} mismatch")

                        if remaining_files:
                            logger.warning(
                                f"Archive {archive_id}: Only found {found_count} of "
                                f"{len(normalized_map)} target files. Missing: {remaining_files}"
                            )
                    finally:
                        # Ensure bitstream is closed, especially important for tape devices
                        if hasattr(bitstream, "close"):
                            bitstream.close()

            if not JobManager.is_cancelled(job_id):
                db_session.query(models.RestoreCart).delete()
                db_session.commit()
                JobManager.add_job_log(job_id, "Restore complete, queue cleared")
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
