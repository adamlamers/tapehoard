import os
import hashlib
import time
import psutil
import threading
import concurrent.futures
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any
from loguru import logger
from sqlalchemy.orm import Session
from app.db import models
from app.db.database import SessionLocal


class JobManager:
    @staticmethod
    def create_job(db: Session, job_type: str) -> models.Job:
        job = models.Job(job_type=job_type, status="PENDING")
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    @staticmethod
    def start_job(job_id: int):
        db = SessionLocal()
        try:
            job = db.get(models.Job, job_id)
            if job:
                job.status = "RUNNING"
                job.started_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()

    @staticmethod
    def update_job(job_id: int, progress: float, current_task: str):
        db = SessionLocal()
        try:
            job = db.get(models.Job, job_id)
            if job:
                job.progress = progress
                job.current_task = current_task
                db.commit()
        finally:
            db.close()

    @staticmethod
    def complete_job(job_id: int):
        db = SessionLocal()
        try:
            job = db.get(models.Job, job_id)
            if job:
                job.status = "COMPLETED"
                job.progress = 100.0
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()

    @staticmethod
    def fail_job(job_id: int, error_message: str):
        db = SessionLocal()
        try:
            job = db.get(models.Job, job_id)
            if job:
                job.status = "FAILED"
                job.error_message = error_message
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()

    @staticmethod
    def cancel_job(job_id: int):
        db = SessionLocal()
        try:
            job = db.get(models.Job, job_id)
            if job and job.status in ["PENDING", "RUNNING"]:
                job.status = "FAILED"
                job.error_message = "Cancelled by user"
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
        finally:
            db.close()

    @staticmethod
    def is_cancelled(job_id: int) -> bool:
        db = SessionLocal()
        try:
            job = db.get(models.Job, job_id)
            return bool(
                job
                and job.status == "FAILED"
                and job.error_message == "Cancelled by user"
            )
        finally:
            db.close()


class ScannerService:
    def __init__(self):
        self.is_running = False
        self.is_hashing = False
        self.last_run_time: Optional[datetime] = None

        # Metrics
        self.files_processed = 0
        self.files_hashed = 0
        self.files_new = 0
        self.files_modified = 0
        self.total_files_found = 0
        self.bytes_hashed = 0
        self.start_time = 0.0
        self.is_throttled = False
        self.current_path = ""
        self._lock = threading.Lock()
        self._current_iowait = 0.0

        # Stalling Tracker
        self._last_block_time = time.time()
        self._active_hashes: Dict[int, str] = {}  # thread_id -> current_file

        # Throttle Monitor
        self._throttle_thread = threading.Thread(
            target=self._monitor_iowait, daemon=True
        )
        self._throttle_thread.start()

    def _monitor_iowait(self):
        """Background thread to poll system pressure once per second (Efficient)"""
        while True:
            try:
                cpu_times = psutil.cpu_times_percent(interval=1)
                iowait = getattr(cpu_times, "iowait", 0.0)
                with self._lock:
                    self.is_throttled = iowait > 5.0
                    self._current_iowait = iowait
            except Exception:
                time.sleep(1)

    def _set_priority(self, level: str = "normal"):
        """Sets the current process priority. 'normal' or 'background'"""
        try:
            if level == "background":
                os.nice(19)
                if hasattr(psutil.Process(), "ionice"):
                    psutil.Process().ionice(psutil.IOPRIO_CLASS_IDLE)
            else:
                os.nice(0)
                if hasattr(psutil.Process(), "ionice"):
                    psutil.Process().ionice(psutil.IOPRIO_CLASS_BE, value=4)
        except Exception:
            pass

    def compute_sha256(self, file_path: str, job_id: Optional[int] = None) -> str:
        sha256_hash = hashlib.sha256()
        thread_id = threading.get_ident()

        try:
            with open(file_path, "rb") as f:
                with self._lock:
                    self._active_hashes[thread_id] = file_path

                for byte_block in iter(lambda: f.read(1048576), b""):
                    if job_id is not None and JobManager.is_cancelled(job_id):
                        return ""

                    # Efficient throttle check
                    if self.is_throttled:
                        delay = 0.05 if self._current_iowait < 15.0 else 0.2
                        time.sleep(delay)

                    sha256_hash.update(byte_block)

                    with self._lock:
                        self.bytes_hashed += len(byte_block)
                        self._last_block_time = time.time()  # Pulse!

            return sha256_hash.hexdigest()
        except Exception as e:
            logger.error(f"Failed to hash {file_path}: {e}")
            return ""
        finally:
            with self._lock:
                if thread_id in self._active_hashes:
                    del self._active_hashes[thread_id]

    def _format_speed(self) -> str:
        elapsed = time.time() - self.start_time
        if elapsed <= 0:
            return "0 B/s"
        speed = self.bytes_hashed / elapsed
        for unit in ["B/s", "KB/s", "MB/s", "GB/s"]:
            if speed < 1024:
                return f"{speed:.1f} {unit}"
            speed /= 1024
        return f"{speed:.1f} TB/s"

    def scan_sources(self, db: Session, job_id: Optional[int] = None):
        """Metadata Discovery - Runs at Normal Priority"""
        if self.is_running:
            return
        self.is_running = True
        self.files_processed = 0
        self.files_new = 0
        self.files_modified = 0
        self.total_files_found = 0
        self.current_path = ""
        self._set_priority("normal")

        if job_id is not None:
            JobManager.start_job(job_id)

        try:
            from app.api.system import get_exclusion_spec, get_source_roots

            spec = get_exclusion_spec(db)
            roots = get_source_roots(db)
            tracking_rules = db.query(models.TrackedSource).all()
            tracking_map = {s.path: s.action for s in tracking_rules}

            def get_status(path: str) -> Tuple[bool, bool]:
                is_ignored = False
                if spec and spec.match_file(path):
                    is_ignored = True
                applicable = []
                for r_path, action in tracking_map.items():
                    if path == r_path or path.startswith(r_path + "/"):
                        applicable.append((len(r_path), action))
                if not applicable:
                    return not is_ignored, is_ignored
                applicable.sort(key=lambda x: x[0], reverse=True)
                return applicable[0][1] == "include", is_ignored

            now = datetime.now(timezone.utc)
            BATCH_SIZE = 1000
            pending: List[Dict[str, Any]] = []

            # Wake up hashing engine immediately
            threading.Thread(target=self.run_hashing).start()

            for root_path in roots:
                if job_id is not None and JobManager.is_cancelled(job_id):
                    break
                if not os.path.exists(root_path):
                    continue

                for root_dir, dirs, files in os.walk(root_path):
                    if job_id is not None and JobManager.is_cancelled(job_id):
                        break
                    if spec:
                        for d in list(dirs):
                            if spec.match_file(os.path.join(root_dir, d) + "/"):
                                dirs.remove(d)

                    for file in files:
                        full_path = os.path.join(root_dir, file)
                        with self._lock:
                            self.total_files_found += 1
                            self.current_path = root_dir

                        try:
                            st = os.stat(full_path)
                            tracked, ignored = get_status(full_path)
                            pending.append(
                                {
                                    "path": full_path,
                                    "size": st.st_size,
                                    "mtime": st.st_mtime,
                                    "tracked": tracked,
                                    "ignored": ignored,
                                }
                            )
                        except Exception:
                            continue

                        if len(pending) >= BATCH_SIZE:
                            self._sync_metadata_batch(db, pending, now)
                            db.commit()
                            pending = []
                            if job_id is not None:
                                JobManager.update_job(
                                    job_id,
                                    10.0,
                                    f"Discovered {self.total_files_found} items...",
                                )

            if pending:
                self._sync_metadata_batch(db, pending, now)
                db.commit()
            db.commit()

            if job_id is not None and not JobManager.is_cancelled(job_id):
                JobManager.complete_job(job_id)
                self.last_run_time = now

        except Exception as e:
            logger.exception(f"Scan failed: {e}")
            db.rollback()
            if job_id is not None:
                JobManager.fail_job(job_id, str(e))
        finally:
            self.is_running = False

    def _sync_metadata_batch(self, db: Session, batch: List[Dict[str, Any]], now):
        paths = [f["path"] for f in batch]
        existing = {
            r.file_path: r
            for r in db.query(models.FilesystemState)
            .filter(models.FilesystemState.file_path.in_(paths))
            .all()
        }
        for f in batch:
            ext = existing.get(f["path"])
            if not ext:
                with self._lock:
                    self.files_new += 1
                db.add(
                    models.FilesystemState(
                        file_path=f["path"],
                        size=f["size"],
                        mtime=f["mtime"],
                        is_ignored=f["ignored"],
                        last_seen_timestamp=now,
                        is_indexed=False,
                    )
                )
            else:
                if ext.size != f["size"] or ext.mtime != f["mtime"]:
                    ext.is_indexed = False
                if ext.size != f["size"] or ext.mtime != f["mtime"]:
                    with self._lock:
                        self.files_modified += 1
                ext.size = f["size"]
                ext.mtime = f["mtime"]
                ext.is_ignored = f["ignored"]
                ext.last_seen_timestamp = now

            with self._lock:
                self.files_processed += 1

    def run_hashing(self):
        """Content Hashing Engine - Low Priority Background Worker"""
        if self.is_hashing:
            return
        with self._lock:
            self.is_hashing = True

        self._set_priority("background")
        db = SessionLocal()
        job = JobManager.create_job(db, "HASH")
        JobManager.start_job(job.id)

        self.start_time = time.time()
        self.bytes_hashed = 0
        self.files_hashed = 0

        try:
            while True:
                targets = (
                    db.query(models.FilesystemState)
                    .filter(
                        models.FilesystemState.is_indexed.is_(False),
                        models.FilesystemState.is_ignored.is_(False),
                    )
                    .limit(100)
                    .all()
                )

                if not targets:
                    # If discovery is still running, wait for more metadata to hit the DB
                    if self.is_running:
                        time.sleep(2)
                        continue
                    break

                if JobManager.is_cancelled(job.id):
                    break

                workers = os.cpu_count() or 4
                with concurrent.futures.ThreadPoolExecutor(
                    max_workers=workers
                ) as executor:
                    futures = {
                        executor.submit(self.compute_sha256, t.file_path, job.id): t
                        for t in targets
                    }
                    for future in concurrent.futures.as_completed(futures):
                        t = futures[future]
                        h = future.result()
                        if h:
                            t.sha256_hash = h
                            t.is_indexed = True
                            self.files_hashed += 1

                        if self.files_hashed % 5 == 0:
                            # RICH HEARTBEAT STATUS
                            with self._lock:
                                stall_time = time.time() - self._last_block_time
                                is_stalled = stall_time > 60.0

                                active_files = list(self._active_hashes.values())
                                first_active = (
                                    active_files[0].split("/")[-1]
                                    if active_files
                                    else "Waiting..."
                                )

                                status = f"Hashing: {self.files_hashed} objs [{self._format_speed()}] | Active: {first_active}"
                                if is_stalled:
                                    status = (
                                        f"⚠️ STALLED ({int(stall_time)}s) | {status}"
                                    )
                                elif self.is_throttled:
                                    status += " (THROTTLED)"

                            JobManager.update_job(job.id, 50.0, status)
                db.commit()

            JobManager.complete_job(job.id)
        except Exception as e:
            logger.error(f"Hashing job failed: {e}")
            JobManager.fail_job(job.id, str(e))
        finally:
            self.is_hashing = False
            db.close()


scanner_manager = ScannerService()
