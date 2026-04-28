import os
import hashlib
import time
import psutil
import threading
import concurrent.futures
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from loguru import logger
from sqlalchemy.orm import Session
from app.db import models
from app.db.database import SessionLocal


class JobManager:
    """Manages operational job states and persistence."""

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
            job_record = db_session.get(models.Job, job_id)
            if job_record:
                job_record.status = "RUNNING"
                job_record.started_at = datetime.now(timezone.utc)
                db_session.commit()

    @staticmethod
    def update_job(job_id: int, progress: float, current_task: str):
        """Updates the progress and current task description for a job."""
        with SessionLocal() as db_session:
            job_record = db_session.get(models.Job, job_id)
            if job_record:
                job_record.progress = progress
                job_record.current_task = current_task
                db_session.commit()

    @staticmethod
    def complete_job(job_id: int):
        """Marks a job as successfully completed."""
        with SessionLocal() as db_session:
            job_record = db_session.get(models.Job, job_id)
            if job_record:
                job_record.status = "COMPLETED"
                job_record.progress = 100.0
                job_record.completed_at = datetime.now(timezone.utc)
                db_session.commit()

    @staticmethod
    def fail_job(job_id: int, error_message: str):
        """Marks a job as failed and records the error message."""
        with SessionLocal() as db_session:
            job_record = db_session.get(models.Job, job_id)
            if job_record:
                job_record.status = "FAILED"
                job_record.error_message = error_message
                job_record.completed_at = datetime.now(timezone.utc)
                db_session.commit()

    @staticmethod
    def cancel_job(job_id: int):
        """Submits a cancellation request for a pending or running job."""
        with SessionLocal() as db_session:
            job_record = db_session.get(models.Job, job_id)
            if job_record and job_record.status in ["PENDING", "RUNNING"]:
                job_record.status = "FAILED"
                job_record.error_message = "Cancelled by user"
                job_record.completed_at = datetime.now(timezone.utc)
                db_session.commit()

    @staticmethod
    def is_cancelled(job_id: int) -> bool:
        """Checks if a job has been cancelled by the user."""
        with SessionLocal() as db_session:
            job_record = db_session.get(models.Job, job_id)
            return bool(
                job_record
                and job_record.status == "FAILED"
                and job_record.error_message == "Cancelled by user"
            )


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
            except Exception as monitor_error:
                logger.debug(f"I/O Monitor pulse failed: {monitor_error}")
                time.sleep(1)

    def _set_process_priority(self, level: str = "normal"):
        """Adjusts CPU and I/O priority for the current process."""
        try:
            if level == "background":
                os.nice(19)
                if hasattr(psutil.Process(), "ionice") and hasattr(
                    psutil, "IOPRIO_CLASS_IDLE"
                ):
                    process_handle = psutil.Process()
                    process_handle.ionice(psutil.IOPRIO_CLASS_IDLE)
            else:
                os.nice(0)
                if hasattr(psutil.Process(), "ionice") and hasattr(
                    psutil, "IOPRIO_CLASS_BE"
                ):
                    process_handle = psutil.Process()
                    process_handle.ionice(psutil.IOPRIO_CLASS_BE, value=4)
        except Exception as priority_error:
            logger.debug(f"Priority adjustment restricted: {priority_error}")

    def compute_sha256(self, file_path: str, job_id: Optional[int] = None) -> str:
        """Computes the SHA-256 hash of a file with high-velocity block processing."""
        hash_engine = hashlib.sha256()

        # Increase block size to 8MB for high-speed NVMe saturation
        # and use local counter to minimize lock contention
        BLOCK_SIZE = 8 * 1024 * 1024
        local_processed_bytes = 0
        SYNC_THRESHOLD = 128 * 1024 * 1024  # Sync metrics every 128MB

        try:
            with open(file_path, "rb") as file_handle:
                while True:
                    if job_id is not None and JobManager.is_cancelled(job_id):
                        return ""

                    # Dynamic throttling - only check periodically to save cycles
                    if self.is_throttled:
                        throttle_delay = 0.05 if self._current_iowait < 15.0 else 0.2
                        time.sleep(throttle_delay)

                    byte_block = file_handle.read(BLOCK_SIZE)
                    if not byte_block:
                        break

                    hash_engine.update(byte_block)
                    local_processed_bytes += len(byte_block)

                    # Batch sync metrics to global counter
                    if local_processed_bytes >= SYNC_THRESHOLD:
                        with self._metrics_lock:
                            self.bytes_hashed += local_processed_bytes
                        local_processed_bytes = 0

                # Final remaining sync
                if local_processed_bytes > 0:
                    with self._metrics_lock:
                        self.bytes_hashed += local_processed_bytes

            return hash_engine.hexdigest()
        except OSError as io_error:
            logger.error(f"IO Error during hashing {file_path}: {io_error}")
            return ""
        except Exception as generic_error:
            logger.error(f"Unexpected error hashing {file_path}: {generic_error}")
            return ""

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
        """Executes Phase 1: Fast Metadata Discovery."""
        if self.is_running:
            logger.warning("Discovery scan already active.")
            return

        self.is_running = True
        self.files_processed = 0
        self.files_new = 0
        self.files_modified = 0
        self.total_files_found = 0
        self.current_path = ""
        self._set_process_priority("normal")

        if job_id is not None:
            JobManager.start_job(job_id)

        try:
            from app.api.system import get_exclusion_spec, get_source_roots

            exclusion_spec = get_exclusion_spec(db_session)
            source_roots = get_source_roots(db_session)
            tracking_rules = db_session.query(models.TrackedSource).all()
            tracking_map = {rule.path: rule.action for rule in tracking_rules}

            def resolve_tracking(absolute_path: str) -> bool:
                # 1. Global Exclusions
                if exclusion_spec and exclusion_spec.match_file(absolute_path):
                    return True

                # 2. User Tracking Policy
                applicable_rules = []
                for rule_path, action in tracking_map.items():
                    if absolute_path == rule_path or absolute_path.startswith(
                        rule_path + "/"
                    ):
                        applicable_rules.append((len(rule_path), action))

                if not applicable_rules:
                    # Default to NOT ignored if in a source root and no rules match
                    return False

                applicable_rules.sort(key=lambda x: x[0], reverse=True)
                return applicable_rules[0][1] == "exclude"

            current_timestamp = datetime.now(timezone.utc)
            BATCH_SIZE = 1000
            pending_metadata: List[Dict[str, Any]] = []

            # Initialize Phase 2 in background
            threading.Thread(target=self.run_hashing).start()

            for root_base in source_roots:
                if job_id is not None and JobManager.is_cancelled(job_id):
                    break
                if not os.path.exists(root_base):
                    continue

                for current_dir, sub_dirs, file_names in os.walk(root_base):
                    if job_id is not None and JobManager.is_cancelled(job_id):
                        break

                    # Prune directories early to save syscalls
                    if exclusion_spec:
                        for directory_name in list(sub_dirs):
                            full_dir_path = os.path.join(current_dir, directory_name)
                            if exclusion_spec.match_file(full_dir_path + "/"):
                                sub_dirs.remove(directory_name)

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

            if job_id is not None and not JobManager.is_cancelled(job_id):
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
                        is_indexed=False,
                    )
                )
            else:
                metadata_changed = (
                    record.size != file_meta["size"]
                    or record.mtime != file_meta["mtime"]
                )
                if metadata_changed:
                    record.is_indexed = False
                    with self._metrics_lock:
                        self.files_modified += 1

                record.size = file_meta["size"]
                record.mtime = file_meta["mtime"]
                record.is_ignored = file_meta["ignored"]
                record.last_seen_timestamp = timestamp

            with self._metrics_lock:
                self.files_processed += 1

    def run_hashing(self):
        """Executes Phase 2: Background Content Hashing."""
        if self.is_hashing:
            return
        with self._metrics_lock:
            self.is_hashing = True

        self._set_process_priority("background")

        with SessionLocal() as db_session:
            hashing_job = JobManager.create_job(db_session, "HASH")
            JobManager.start_job(hashing_job.id)

            self.start_time = time.time()
            self.bytes_hashed = 0
            self.files_hashed = 0

            try:
                while True:
                    # Find unindexed work
                    hashing_targets = (
                        db_session.query(models.FilesystemState)
                        .filter(
                            models.FilesystemState.is_indexed.is_(False),
                            models.FilesystemState.is_ignored.is_(False),
                        )
                        .limit(100)
                        .all()
                    )

                    if not hashing_targets:
                        if self.is_running:
                            time.sleep(2)
                            continue
                        break

                    if JobManager.is_cancelled(hashing_job.id):
                        break

                    max_workers = os.cpu_count() or 4
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=max_workers
                    ) as hashing_executor:
                        future_to_file = {
                            hashing_executor.submit(
                                self.compute_sha256, target.file_path, hashing_job.id
                            ): target
                            for target in hashing_targets
                        }

                        for future in concurrent.futures.as_completed(future_to_file):
                            target_record = future_to_file[future]
                            computed_hash = future.result()

                            if computed_hash:
                                target_record.sha256_hash = computed_hash
                                target_record.is_indexed = True
                                self.files_hashed += 1

                            if self.files_hashed % 5 == 0:
                                status_msg = f"Hashing Fleet: {self.files_hashed} objects processed [{self._format_throughput()}]"
                                if self.is_throttled:
                                    status_msg += " (THROTTLED)"
                                JobManager.update_job(hashing_job.id, 50.0, status_msg)

                    db_session.commit()

                JobManager.complete_job(hashing_job.id)
            except Exception as hashing_error:
                logger.error(f"Background hashing failed: {hashing_error}")
                JobManager.fail_job(hashing_job.id, str(hashing_error))
            finally:
                self.is_hashing = False


scanner_manager = ScannerService()
