import concurrent.futures
import hashlib
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psutil
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import ObjectDeletedError, StaleDataError

from app.db import models
from app.db.database import SessionLocal


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
        """Marks a job as successfully completed if it is still active."""
        with SessionLocal() as db_session:
            try:
                job_record = db_session.get(models.Job, job_id)
                if job_record and job_record.status in ("PENDING", "RUNNING"):
                    job_record.status = "COMPLETED"
                    job_record.progress = 100.0
                    job_record.completed_at = datetime.now(timezone.utc)
                    db_session.commit()
            except (StaleDataError, Exception) as e:
                db_session.rollback()
                logger.debug(f"JobManager.complete_job failed for {job_id}: {e}")

    @staticmethod
    def fail_job(job_id: int, error_message: str):
        """Marks a job as failed if it is still active."""
        with SessionLocal() as db_session:
            try:
                job_record = db_session.get(models.Job, job_id)
                if job_record and job_record.status in ("PENDING", "RUNNING"):
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
        while self.is_running or self.is_hashing:
            try:
                cpu_times = psutil.cpu_times_percent(interval=0.1)
                iowait_value = getattr(cpu_times, "iowait", 0.0)
                with self._metrics_lock:
                    self.is_throttled = iowait_value > 5.0
                    self._current_iowait = iowait_value
            except Exception:
                pass
            # Use short sleep in a loop so we notice when the flags change
            for _ in range(20):
                if not (self.is_running or self.is_hashing):
                    return
                time.sleep(0.1)

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
            from app.api.common import get_exclusion_spec, get_source_roots

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

                # How many files to pull from DB per iteration
                FETCH_LIMIT = 400

                while self.is_hashing:
                    # Find unindexed work (exclude deleted files - they cannot be hashed)
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

                    # Hash files using Python hashlib via thread pool
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

                        for future in concurrent.futures.as_completed(future_to_file):
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
                                    (self.files_hashed / max(total_pending, 1)) * 100,
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

        except ObjectDeletedError:
            logger.debug(
                "Background hashing aborted: Job was deleted by another process"
            )
            # Exit gracefully - another process cancelled this job
            try:
                with self._metrics_lock:
                    self.is_hashing = False
            except Exception:
                pass
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
