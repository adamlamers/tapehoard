import concurrent.futures
import hashlib
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import psutil
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.db import models
from app.db.database import SessionLocal

# Fast file discovery via `find -printf` (GNU find or compatible).
# Detected once at import time; falls back to os.walk if unavailable.
_FAST_FIND_BINARY: Optional[str] = None

# Fast hashing via `sha256sum` or `shasum`.
# Detected once at import time; falls back to Python hashlib if unavailable.
_FAST_HASH_BINARY: Optional[str] = None


def _detect_fast_find() -> Optional[str]:
    """Check if a `find` binary with `-printf` support is available.

    Tries `gfind` (GNU find via Homebrew on macOS) first, then `find`.
    Returns the binary path if `-printf` works, otherwise ``None``.
    """
    for candidate in ("gfind", "find"):
        binary = shutil.which(candidate)
        if binary is None:
            continue
        try:
            result = subprocess.run(
                [binary, "/tmp", "-maxdepth", "0", "-printf", "%f\n"],
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip() == b"tmp":
                return binary
        except Exception:
            continue
    return None


def _detect_fast_hash() -> Optional[str]:
    """Check if a SHA-256 binary is available for batch hashing.

    Tries `sha256sum` (GNU coreutils, Linux/Homebrew) then `shasum` (macOS).
    Returns the binary path if it works, otherwise ``None``.
    """
    # Try sha256sum first (Linux, Homebrew gnu-coreutils)
    binary = shutil.which("sha256sum")
    if binary:
        try:
            result = subprocess.run(
                [binary, "/dev/null"],
                capture_output=True,
                timeout=5,
            )
            if (
                result.returncode == 0
                and b"e3b0c44298fc1c149afbf4c8996fb924" in result.stdout
            ):
                return binary
        except Exception:
            pass

    # Try shasum (macOS default)
    binary = shutil.which("shasum")
    if binary:
        try:
            result = subprocess.run(
                [binary, "-a", "256", "/dev/null"],
                capture_output=True,
                timeout=5,
            )
            if (
                result.returncode == 0
                and b"e3b0c44298fc1c149afbf4c8996fb924" in result.stdout
            ):
                return binary
        except Exception:
            pass

    return None


def _init_fast_features() -> Tuple[Optional[str], Optional[str]]:
    global _FAST_FIND_BINARY, _FAST_HASH_BINARY
    _FAST_FIND_BINARY = _detect_fast_find()
    _FAST_HASH_BINARY = _detect_fast_hash()

    if _FAST_FIND_BINARY:
        logger.info(f"Fast file discovery enabled: using {_FAST_FIND_BINARY} -printf")
    else:
        logger.info("Fast file discovery unavailable: falling back to os.walk")

    if _FAST_HASH_BINARY:
        logger.info(f"Fast hashing enabled: using {_FAST_HASH_BINARY}")
    else:
        logger.info("Fast hashing unavailable: falling back to Python hashlib")

    return _FAST_FIND_BINARY, _FAST_HASH_BINARY


_FAST_FIND_BINARY, _FAST_HASH_BINARY = _init_fast_features()


def _hash_file_batch_fast(
    file_paths: List[str], binary: str
) -> Dict[str, Optional[str]]:
    """Hash a batch of files using a native SHA-256 binary.

    Streams output line-by-line via subprocess.Popen for incremental progress.

    Args:
        file_paths: Paths to hash.
        binary: Path to sha256sum or shasum.

    Returns a mapping of file_path -> hex_digest (or None on failure).
    """
    results: Dict[str, Optional[str]] = {}

    if not file_paths:
        return results

    # Build command: shasum needs -a 256 prefix, sha256sum doesn't
    if binary.endswith("sha256sum"):
        cmd = [binary, "--"] + file_paths
    else:
        # shasum
        cmd = [binary, "-a", "256", "--"] + file_paths

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        # Stream output line-by-line for incremental progress
        if proc.stdout is None:
            return results
        for line in iter(proc.stdout.readline, b""):
            line = line.strip()
            if not line:
                continue
            # Format: "<hash>  <path>" or "<hash> *<path>"
            parts = line.split(b"  ", 1)
            if len(parts) != 2:
                # Try single space with binary marker: "<hash> *<path>"
                parts = line.split(b" *", 1)
                if len(parts) != 2:
                    continue

            file_hash = parts[0].decode("ascii", errors="replace").lower()
            raw_path = parts[1].decode("utf-8", errors="replace")

            # sha256sum may escape backslashes in filenames; handle common case
            clean_path = raw_path.replace("\\\\", "\\")

            results[clean_path] = file_hash

        proc.stdout.close()
        proc.wait()

    except Exception as e:
        logger.error(f"Native hash batch failed: {e}")

    return results


def _discover_files_fast(
    root_base: str,
    job_id: Optional[int],
    batch_size: int,
    current_timestamp,
    resolve_tracking,
    sync_metadata_batch,
    metrics_lock,
    metrics,
    db_session: Session,
) -> Tuple[int, int]:
    """Walk a tree using `find -printf` for fast metadata extraction.

    Streams output line-by-line via subprocess.Popen so progress updates
    appear as files are discovered instead of waiting for find to finish.

    Returns (files_found, files_batched) counts.
    """
    total_files_found = 0
    files_batched = 0
    pending_metadata: List[Dict[str, Any]] = []

    # -printf format: path\tsize\tmtime (tab-separated; split from right for safety)
    find_binary = _FAST_FIND_BINARY
    assert find_binary is not None
    cmd = [
        find_binary,
        root_base,
        "-type",
        "f",
        "-printf",
        "%p\t%s\t%T@\n",
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if proc.stdout is None:
            logger.error(
                f"Fast file discovery failed: could not open stdout for {root_base}"
            )
            return 0, 0
    except Exception as e:
        logger.error(f"Fast file discovery failed for {root_base}: {e}")
        return 0, 0

    # Stream output line by line (tab-separated: path\tsize\tmtime)
    for line in iter(proc.stdout.readline, b""):
        if job_id is not None and JobManager.is_cancelled(job_id):
            break

        if not line.strip():
            continue

        # Split from right: mtime and size are always numeric
        parts = line.split(b"\t")
        if len(parts) < 3:
            continue

        # First n-2 parts may be path components (tabs in filename are rare)
        full_file_path = b"\t".join(parts[:-2]).decode("utf-8", errors="replace")
        try:
            file_size = int(parts[-2])
            file_mtime = float(parts[-1])
        except (ValueError, IndexError):
            continue

        total_files_found += 1
        with metrics_lock:
            metrics["total_files_found"] = total_files_found
            metrics["current_path"] = os.path.dirname(full_file_path)

        is_ignored = resolve_tracking(full_file_path)
        pending_metadata.append(
            {
                "path": full_file_path,
                "size": file_size,
                "mtime": file_mtime,
                "ignored": is_ignored,
            }
        )

        if len(pending_metadata) >= batch_size:
            sync_metadata_batch(db_session, pending_metadata, current_timestamp)
            db_session.commit()
            files_batched += len(pending_metadata)
            pending_metadata = []
            if job_id is not None:
                JobManager.update_job(
                    job_id,
                    10.0,
                    f"Discovered {total_files_found} items...",
                )

    proc.stdout.close()
    proc.wait()

    # Flush remaining batch
    if pending_metadata:
        sync_metadata_batch(db_session, pending_metadata, current_timestamp)
        db_session.commit()
        files_batched += len(pending_metadata)

    return total_files_found, files_batched


class JobManager:
    """Manages operational job states and persistence with high resilience for background threads."""

    @staticmethod
    def create_job(db_session: Session, job_type: str) -> models.Job:
        """Creates a new job record in the database."""
        job_record = models.Job(job_type=job_type, status="PENDING")
        db_session.add(job_record)
        db_session.commit()
        db_session.refresh(job_record)
        return job_record

    @staticmethod
    def start_job(job_id: int):
        """Marks a job as running and sets the start timestamp."""
        with SessionLocal() as db_session:
            try:
                job_record = db_session.get(models.Job, job_id)
                if job_record:
                    job_record.status = "RUNNING"
                    job_record.started_at = datetime.now(timezone.utc)
                    db_session.commit()
            except (StaleDataError, Exception) as e:
                db_session.rollback()
                logger.debug(f"JobManager.start_job failed for {job_id}: {e}")

    @staticmethod
    def update_job(job_id: int, progress: float, current_task: str):
        """Updates the progress and current task description for a job."""
        with SessionLocal() as db_session:
            try:
                job_record = db_session.get(models.Job, job_id)
                if job_record:
                    job_record.progress = progress
                    job_record.current_task = current_task
                    db_session.commit()
            except (StaleDataError, Exception) as e:
                db_session.rollback()
                logger.debug(f"JobManager.update_job failed for {job_id}: {e}")

    @staticmethod
    def complete_job(job_id: int):
        """Marks a job as successfully completed."""
        with SessionLocal() as db_session:
            try:
                job_record = db_session.get(models.Job, job_id)
                if job_record:
                    job_record.status = "COMPLETED"
                    job_record.progress = 100.0
                    job_record.completed_at = datetime.now(timezone.utc)
                    db_session.commit()
            except (StaleDataError, Exception) as e:
                db_session.rollback()
                logger.debug(f"JobManager.complete_job failed for {job_id}: {e}")

    @staticmethod
    def fail_job(job_id: int, error_message: str):
        """Marks a job as failed and records the error message."""
        with SessionLocal() as db_session:
            try:
                job_record = db_session.get(models.Job, job_id)
                if job_record:
                    job_record.status = "FAILED"
                    job_record.error_message = error_message
                    job_record.completed_at = datetime.now(timezone.utc)
                    db_session.commit()
            except (StaleDataError, Exception) as e:
                db_session.rollback()
                logger.debug(f"JobManager.fail_job failed for {job_id}: {e}")

    @staticmethod
    def add_job_log(job_id: int, message: str):
        """Appends a log entry to a job's log history."""
        with SessionLocal() as db_session:
            try:
                log_entry = models.JobLog(job_id=job_id, message=message)
                db_session.add(log_entry)
                db_session.commit()
            except (StaleDataError, Exception) as e:
                db_session.rollback()
                logger.debug(f"JobManager.add_job_log failed for {job_id}: {e}")

    @staticmethod
    def cancel_job(job_id: int):
        """Submits a cancellation request for a pending or running job."""
        with SessionLocal() as db_session:
            try:
                job_record = db_session.get(models.Job, job_id)
                if job_record and job_record.status in ["PENDING", "RUNNING"]:
                    job_record.status = "FAILED"
                    job_record.is_cancelled = True
                    job_record.error_message = "Cancelled by user"
                    job_record.completed_at = datetime.now(timezone.utc)
                    db_session.commit()
            except (StaleDataError, Exception) as e:
                db_session.rollback()
                logger.debug(f"JobManager.cancel_job failed for {job_id}: {e}")

    @staticmethod
    def is_cancelled(job_id: int) -> bool:
        """Checks if a job has been cancelled by the user."""
        with SessionLocal() as db_session:
            try:
                job_record = db_session.get(models.Job, job_id)
                return bool(job_record and job_record.is_cancelled)
            except Exception:
                return False


class ScannerService:
    """Handles recursive filesystem discovery and content indexing."""

    def __init__(self):
        self.is_running: bool = False
        self.is_hashing: bool = False
        self.last_run_time: Optional[datetime] = None

        # Thread-safe Metrics
        self.files_processed: int = 0
        self.files_hashed: int = 0
        self.files_new: int = 0
        self.files_modified: int = 0
        self.files_missing: int = 0
        self.total_files_found: int = 0
        self.bytes_hashed: int = 0
        self.start_time: float = 0.0
        self.is_throttled: bool = False
        self.current_path: str = ""
        self._metrics_lock = threading.Lock()
        self._current_iowait: float = 0.0

        # Background Monitors
        self._throttle_thread = threading.Thread(
            target=self._monitor_iowait, daemon=True
        )
        self._throttle_thread.start()

    def _monitor_iowait(self):
        """Polls system I/O pressure to enable dynamic back-off."""
        while True:
            try:
                cpu_times = psutil.cpu_times_percent(interval=1)
                iowait_value = getattr(cpu_times, "iowait", 0.0)
                with self._metrics_lock:
                    self.is_throttled = iowait_value > 5.0
                    self._current_iowait = iowait_value
            except Exception:
                pass
            time.sleep(2)

    def _set_process_priority(self, level: str):
        """Adjusts the CPU and I/O priority of the current process."""
        try:
            p = psutil.Process(os.getpid())
            if level == "background":
                if hasattr(p, "ionice"):
                    p.ionice(
                        psutil.IOPRIO_CLASS_IDLE  # ty: ignore[unresolved-attribute]
                    )
                p.nice(19)
            else:
                if hasattr(p, "ionice"):
                    p.ionice(psutil.IOPRIO_CLASS_BE)  # ty: ignore[unresolved-attribute]
                p.nice(0)
        except Exception:
            pass

    def compute_sha256(
        self, file_path: str, job_id: Optional[int] = None
    ) -> Optional[str]:
        """Calculates the SHA-256 hash of a file with dynamic throttling."""
        try:
            sha256_hash = hashlib.sha256()
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(1024 * 1024), b""):
                    if job_id is not None and JobManager.is_cancelled(job_id):
                        return None

                    # Dynamic Throttling: If system I/O is high, sleep between blocks
                    if self.is_throttled:
                        time.sleep(0.1)

                    sha256_hash.update(byte_block)
                    with self._metrics_lock:
                        self.bytes_hashed += len(byte_block)
            return sha256_hash.hexdigest()
        except (OSError, PermissionError):
            return None

    def _format_throughput(self) -> str:
        """Calculates and formats current hashing speed."""
        elapsed_seconds = time.time() - self.start_time
        if elapsed_seconds <= 0:
            return "0 B/s"
        bytes_per_second = self.bytes_hashed / elapsed_seconds
        for unit in ["B/s", "KB/s", "MB/s", "GB/s"]:
            if bytes_per_second < 1024:
                return f"{bytes_per_second:.1f} {unit}"
            bytes_per_second /= 1024
        return f"{bytes_per_second:.1f} TB/s"

    def scan_sources(self, db_session: Session, job_id: Optional[int] = None):
        """Executes Phase 1: Metadata discovery and index synchronization."""
        if self.is_running:
            return
        self.is_running = True

        if job_id is not None:
            JobManager.start_job(job_id)
            JobManager.update_job(job_id, 0.0, "Starting system scan...")
            JobManager.add_job_log(job_id, "Starting system scan")

        self._set_process_priority("normal")
        with self._metrics_lock:
            self.files_processed = 0
            self.files_new = 0
            self.files_modified = 0
            self.files_missing = 0
            self.total_files_found = 0

        try:
            from app.api.system import get_exclusion_spec, get_source_roots

            exclusion_spec = get_exclusion_spec(db_session)
            source_roots = get_source_roots(db_session)
            tracking_rules = db_session.query(models.TrackedSource).all()
            tracking_map = {rule.path: rule.action for rule in tracking_rules}

            def resolve_tracking(absolute_path: str) -> bool:
                # 1. User Tracking Policy (Explicit overrides)
                applicable_rules = []
                for rule_path, action in tracking_map.items():
                    if absolute_path == rule_path or absolute_path.startswith(
                        rule_path + "/"
                    ):
                        applicable_rules.append((len(rule_path), action))

                if applicable_rules:
                    # Most specific rule wins
                    applicable_rules.sort(key=lambda x: x[0], reverse=True)
                    return applicable_rules[0][1] == "exclude"

                # 2. Global Exclusions (Default automatic behavior)
                if exclusion_spec and exclusion_spec.match_file(absolute_path):
                    return True

                return False

            current_timestamp = datetime.now(timezone.utc)
            BATCH_SIZE = 1000
            pending_metadata: List[Dict[str, Any]] = []

            # Initialize Phase 2 in background
            hashing_thread = threading.Thread(target=self.run_hashing)
            hashing_thread.daemon = True
            hashing_thread.start()

            for root_base in source_roots:
                if job_id is not None and JobManager.is_cancelled(job_id):
                    break
                if not os.path.exists(root_base):
                    continue

                if _FAST_FIND_BINARY:
                    # Fast path: GNU find -printf (metadata extracted in C)
                    metrics = {
                        "total_files_found": 0,
                        "current_path": root_base,
                    }
                    found, _ = _discover_files_fast(
                        root_base,
                        job_id,
                        BATCH_SIZE,
                        current_timestamp,
                        resolve_tracking,
                        self._sync_metadata_batch,
                        self._metrics_lock,
                        metrics,
                        db_session,
                    )
                    with self._metrics_lock:
                        self.total_files_found += found
                else:
                    # Compatibility path: Python os.walk + os.stat
                    for current_dir, _sub_dirs, file_names in os.walk(root_base):
                        if job_id is not None and JobManager.is_cancelled(job_id):
                            break

                        for name in file_names:
                            full_file_path = os.path.join(current_dir, name)
                            with self._metrics_lock:
                                self.total_files_found += 1
                                self.current_path = current_dir

                            try:
                                file_stats = os.stat(full_file_path)
                                is_ignored = resolve_tracking(full_file_path)
                                pending_metadata.append(
                                    {
                                        "path": full_file_path,
                                        "size": file_stats.st_size,
                                        "mtime": file_stats.st_mtime,
                                        "ignored": is_ignored,
                                    }
                                )
                            except (OSError, FileNotFoundError):
                                continue

                            if len(pending_metadata) >= BATCH_SIZE:
                                self._sync_metadata_batch(
                                    db_session, pending_metadata, current_timestamp
                                )
                                db_session.commit()
                                pending_metadata = []
                                if job_id is not None:
                                    JobManager.update_job(
                                        job_id,
                                        10.0,
                                        f"Discovered {self.total_files_found} items...",
                                    )

            if pending_metadata:
                self._sync_metadata_batch(
                    db_session, pending_metadata, current_timestamp
                )
                db_session.commit()

            # Detect files present in DB but not found during this scan
            stale_query = (
                db_session.query(models.FilesystemState)
                .filter(
                    models.FilesystemState.last_seen_timestamp < current_timestamp,
                    models.FilesystemState.is_deleted.is_(False),
                    models.FilesystemState.is_ignored.is_(False),
                )
                .yield_per(1000)
            )
            if not JobManager.is_cancelled(job_id) if job_id else True:
                missing_count = 0
                for record in stale_query:
                    if not os.path.exists(record.file_path):
                        record.is_deleted = True
                        missing_count += 1
                    else:
                        record.is_deleted = False
                        record.missing_acknowledged_at = None
                        record.last_seen_timestamp = current_timestamp
                db_session.commit()
                if missing_count:
                    with self._metrics_lock:
                        self.files_missing += missing_count
                    logger.info(
                        f"Scan detected {missing_count} files missing from disk (marked as deleted)"
                    )

            if job_id is not None and not JobManager.is_cancelled(job_id):
                JobManager.add_job_log(
                    job_id,
                    f"Scan complete: {self.files_new} new, {self.files_modified} modified, {self.files_missing} missing",
                )
                JobManager.complete_job(job_id)
                self.last_run_time = current_timestamp

        except Exception as scan_error:
            logger.exception(f"Metadata discovery failed: {scan_error}")
            db_session.rollback()
            if job_id is not None:
                JobManager.fail_job(job_id, str(scan_error))
        finally:
            self.is_running = False

    def _sync_metadata_batch(
        self, db_session: Session, batch: List[Dict[str, Any]], timestamp: datetime
    ):
        """Synchronizes a batch of metadata with the database index."""
        file_paths = [file_meta["path"] for file_meta in batch]

        # Batch Fetch Existing Metadata (Chunked for SQLite limits)
        existing_records = {}
        SQLITE_VARIABLE_LIMIT = 500
        for i in range(0, len(file_paths), SQLITE_VARIABLE_LIMIT):
            chunk = file_paths[i : i + SQLITE_VARIABLE_LIMIT]
            chunk_records = (
                db_session.query(models.FilesystemState)
                .filter(models.FilesystemState.file_path.in_(chunk))
                .all()
            )
            for record in chunk_records:
                existing_records[record.file_path] = record

        for file_meta in batch:
            record = existing_records.get(file_meta["path"])
            if not record:
                with self._metrics_lock:
                    self.files_new += 1
                db_session.add(
                    models.FilesystemState(
                        file_path=file_meta["path"],
                        size=file_meta["size"],
                        mtime=file_meta["mtime"],
                        is_ignored=file_meta["ignored"],
                        last_seen_timestamp=timestamp,
                    )
                )
            else:
                metadata_changed = (
                    record.size != file_meta["size"]
                    or record.mtime != file_meta["mtime"]
                )
                if metadata_changed:
                    record.sha256_hash = None
                    with self._metrics_lock:
                        self.files_modified += 1

                record.size = file_meta["size"]
                record.mtime = file_meta["mtime"]
                record.is_ignored = file_meta["ignored"]
                record.last_seen_timestamp = timestamp

            with self._metrics_lock:
                self.files_processed += 1

    def stop(self):
        """Signals background threads to stop and clears operational flags."""
        with self._metrics_lock:
            self.is_running = False
            self.is_hashing = False
        logger.info("Scanner service shutdown signaled.")

    def run_hashing(self):
        """Executes Phase 2: Background Content Hashing."""
        if self.is_hashing:
            return
        with self._metrics_lock:
            self.is_hashing = True

        self._set_process_priority("background")

        try:
            with SessionLocal() as db_session:
                hashing_job = JobManager.create_job(db_session, "HASH")
                JobManager.start_job(hashing_job.id)

                self.start_time = time.time()
                self.bytes_hashed = 0
                self.files_hashed = 0

                # Count total work pending for progress reporting
                total_pending = (
                    db_session.query(models.FilesystemState)
                    .filter(
                        models.FilesystemState.sha256_hash.is_(None),
                        models.FilesystemState.is_ignored.is_(False),
                        models.FilesystemState.is_deleted.is_(False),
                    )
                    .count()
                )

                # Fast hash batch size: more files per batch reduces subprocess overhead
                HASH_BATCH_SIZE = 100 if _FAST_HASH_BINARY else 100
                # How many files to pull from DB per iteration
                FETCH_LIMIT = HASH_BATCH_SIZE * 4

                while self.is_hashing:
                    # Find unindexed work (exclude deleted files)
                    hashing_targets = (
                        db_session.query(models.FilesystemState)
                        .filter(
                            models.FilesystemState.sha256_hash.is_(None),
                            models.FilesystemState.is_ignored.is_(False),
                            models.FilesystemState.is_deleted.is_(False),
                        )
                        .limit(FETCH_LIMIT)
                        .all()
                    )

                    if not hashing_targets:
                        # If we are in 'Phase 1' (discovery), wait for more files to appear
                        if self.is_running:
                            time.sleep(1)
                            continue
                        # Otherwise, we are done
                        break

                    if JobManager.is_cancelled(hashing_job.id):
                        break

                    if _FAST_HASH_BINARY:
                        # Fast path: batch files to native sha256sum/shasum
                        # Group into sub-batches of HASH_BATCH_SIZE for parallel processing
                        file_paths = [t.file_path for t in hashing_targets]
                        path_to_record = {t.file_path: t for t in hashing_targets}

                        sub_batches = [
                            file_paths[i : i + HASH_BATCH_SIZE]
                            for i in range(0, len(file_paths), HASH_BATCH_SIZE)
                        ]

                        max_workers = min(os.cpu_count() or 4, len(sub_batches))
                        with concurrent.futures.ThreadPoolExecutor(
                            max_workers=max_workers
                        ) as hashing_executor:
                            future_to_batch = {
                                hashing_executor.submit(
                                    _hash_file_batch_fast,
                                    batch,
                                    _FAST_HASH_BINARY,
                                ): batch
                                for batch in sub_batches
                            }

                            for future in concurrent.futures.as_completed(
                                future_to_batch
                            ):
                                if not self.is_hashing:
                                    break

                                batch = future_to_batch[future]
                                try:
                                    batch_results = future.result()
                                except Exception:
                                    continue

                                # Apply hashes and detect missing files ONLY for this batch
                                for file_path in batch:
                                    target_record = path_to_record.get(file_path)
                                    if not target_record:
                                        continue
                                    if file_path in batch_results:
                                        target_record.sha256_hash = batch_results[
                                            file_path
                                        ]
                                        with self._metrics_lock:
                                            self.bytes_hashed += target_record.size or 0
                                            self.files_hashed += 1
                                            # Report progress incrementally as files complete
                                            if self.files_hashed % 5 == 0:
                                                progress = min(
                                                    99.9,
                                                    (
                                                        self.files_hashed
                                                        / max(total_pending, 1)
                                                    )
                                                    * 100,
                                                )
                                                JobManager.update_job(
                                                    hashing_job.id,
                                                    progress,
                                                    f"Hashed {self.files_hashed} files ({self._format_throughput()})...",
                                                )
                                    elif not os.path.exists(file_path):
                                        target_record.is_deleted = True
                                        with self._metrics_lock:
                                            self.files_missing += 1

                                # Throttle between sub-batches if I/O pressure is high
                                with self._metrics_lock:
                                    should_throttle = self.is_throttled
                                if should_throttle:
                                    time.sleep(0.5)
                    else:
                        # Compatibility path: Python hashlib via thread pool
                        max_workers = os.cpu_count() or 4
                        with concurrent.futures.ThreadPoolExecutor(
                            max_workers=max_workers
                        ) as hashing_executor:
                            future_to_file = {
                                hashing_executor.submit(
                                    self.compute_sha256,
                                    target.file_path,
                                    hashing_job.id,
                                ): target
                                for target in hashing_targets
                            }

                            for future in concurrent.futures.as_completed(
                                future_to_file
                            ):
                                if not self.is_hashing:
                                    break

                                target_record = future_to_file[future]
                                try:
                                    computed_hash = future.result()
                                except Exception:
                                    continue

                                if computed_hash:
                                    target_record.sha256_hash = computed_hash
                                    self.files_hashed += 1
                                elif not os.path.exists(target_record.file_path):
                                    target_record.is_deleted = True
                                    with self._metrics_lock:
                                        self.files_missing += 1

                                if self.files_hashed % 5 == 0:
                                    progress = min(
                                        99.9,
                                        (self.files_hashed / max(total_pending, 1))
                                        * 100,
                                    )
                                    JobManager.update_job(
                                        hashing_job.id,
                                        progress,
                                        f"Hashed {self.files_hashed} files ({self._format_throughput()})...",
                                    )

                    # Commit batch
                    try:
                        db_session.commit()
                    except (StaleDataError, Exception):
                        db_session.rollback()
                        break

                if not JobManager.is_cancelled(hashing_job.id) and self.is_hashing:
                    JobManager.add_job_log(
                        hashing_job.id,
                        f"Hashing complete: {self.files_hashed} files indexed",
                    )
                    JobManager.complete_job(hashing_job.id)

        except Exception as e:
            logger.error(f"Background hashing failed: {e}")
            # Try to report failure, but don't blow up if JobManager fails too
            try:
                if "hashing_job" in locals():
                    JobManager.fail_job(hashing_job.id, str(e))
            except Exception:
                pass
        finally:
            with self._metrics_lock:
                self.is_hashing = False


scanner_manager = ScannerService()
