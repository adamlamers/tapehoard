import os
import hashlib
import time
import psutil
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any, cast
from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db import models
from app.db.database import SessionLocal
import concurrent.futures
import pathspec
import json


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
            if (
                job
                and job.status == "FAILED"
                and job.error_message == "Cancelled by user"
            ):
                return True
            return False
        finally:
            db.close()


class ScannerService:
    def __init__(self):
        self.is_running = False
        self.last_run_time: Optional[datetime] = None
        self.files_processed = 0
        self.files_hashed = 0
        self.total_files_found = 0
        self.current_path = ""

    def _set_low_priority(self):
        """Sets the current process to a background/low-I/O priority"""
        try:
            # CPU Niceness
            os.nice(19)

            # I/O Niceness (Linux only)
            if hasattr(psutil.Process(), "ionice"):
                p = psutil.Process()
                # IOPRIO_CLASS_IDLE is 3. It only gets I/O when nothing else wants it.
                # If that's too slow, we can use IOPRIO_CLASS_BE (2) with priority 7.
                p.ionice(psutil.IOPRIO_CLASS_IDLE)
                logger.info("Scanner process set to IDLE I/O priority")
        except Exception as e:
            logger.debug(f"Priority adjustment restricted: {e}")

    def _check_iowait_throttle(self):
        """Dynamic sleep if system iowait is high"""
        try:
            # Check system-wide CPU times
            # iowait is index 4 on Linux, 0 elsewhere
            cpu_times = psutil.cpu_times_percent(interval=None)
            iowait = getattr(cpu_times, "iowait", 0.0)

            if iowait > 15.0:
                # Heavy contention detected! Back off.
                time.sleep(0.5)
            elif iowait > 5.0:
                # Moderate contention. Micro-sleep.
                time.sleep(0.05)
        except Exception:
            pass

    def compute_sha256(self, file_path: str, job_id: Optional[int] = None) -> str:
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(1048576), b""):
                    if job_id is not None and JobManager.is_cancelled(job_id):
                        return ""

                    # Apply dynamic throttling based on system pressure
                    self._check_iowait_throttle()

                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except Exception as e:
            logger.error(f"Failed to hash {file_path}: {e}")
            return ""

    def _get_exclusion_spec(self, db: Session) -> Optional[pathspec.PathSpec]:
        setting = (
            db.query(models.SystemSetting)
            .filter(models.SystemSetting.key == "global_exclusions")
            .first()
        )
        if not setting or not setting.value.strip():
            return None
        patterns = [p.strip() for p in setting.value.splitlines() if p.strip()]
        return pathspec.PathSpec.from_lines("gitwildmatch", patterns)

    def _get_source_roots(self, db: Session) -> List[str]:
        setting = (
            db.query(models.SystemSetting)
            .filter(models.SystemSetting.key == "source_roots")
            .first()
        )
        if setting:
            try:
                val = json.loads(setting.value)
                if isinstance(val, list):
                    return [str(v) for v in val]
                return [str(val)]
            except Exception:
                return [str(setting.value)]
        return ["/source_data"]

    def scan_sources(self, db: Session, job_id: Optional[int] = None):
        if self.is_running:
            logger.warning("Scan already in progress")
            return

        self.is_running = True
        self.files_processed = 0
        self.files_hashed = 0
        self.total_files_found = 0

        # Be a polite citizen
        self._set_low_priority()

        if job_id is not None:
            JobManager.start_job(job_id)

        try:
            spec = self._get_exclusion_spec(db)
            roots = self._get_source_roots(db)
            tracking_rules = db.query(models.TrackedSource).all()

            raw_include: List[str] = [
                r.path for r in tracking_rules if r.action == "include"
            ]
            raw_exclude: List[str] = [
                r.path for r in tracking_rules if r.action == "exclude"
            ]
            include_rules = cast(List[str], sorted(raw_include, key=len, reverse=True))
            exclude_rules = cast(List[str], sorted(raw_exclude, key=len, reverse=True))

            def get_tracking_status(path: str) -> Tuple[bool, bool]:
                is_ignored = False
                if spec and spec.match_file(path):
                    is_ignored = True
                for ex in exclude_rules:
                    if path == ex or path.startswith(ex + "/"):
                        for inc in include_rules:
                            if len(inc) > len(ex) and (
                                path == inc or path.startswith(inc + "/")
                            ):
                                return True, is_ignored
                        return False, is_ignored
                for inc in include_rules:
                    if path == inc or path.startswith(inc + "/"):
                        return True, is_ignored
                return not is_ignored, is_ignored

            # --- Discovery Pass ---
            BATCH_SIZE = 1000
            pending_batch: List[Dict[str, Any]] = []
            now = datetime.now(timezone.utc)

            # Maximize thread pool for local SSD hashing
            workers = os.cpu_count() or 4
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                for root_path in roots:
                    if job_id is not None and JobManager.is_cancelled(job_id):
                        break
                    if not os.path.exists(root_path):
                        continue

                    for root_dir, dirs, files in os.walk(root_path):
                        if job_id is not None and JobManager.is_cancelled(job_id):
                            break

                        if spec:
                            original_dirs = list(dirs)
                            for d in original_dirs:
                                if spec.match_file(os.path.join(root_dir, d) + "/"):
                                    dirs.remove(d)

                        for file in files:
                            if job_id is not None and JobManager.is_cancelled(job_id):
                                break
                            full_path = os.path.join(root_dir, file)
                            self.total_files_found += 1

                            try:
                                stats = os.stat(full_path)
                                tracked, ignored = get_tracking_status(full_path)
                                pending_batch.append(
                                    {
                                        "path": full_path,
                                        "size": stats.st_size,
                                        "mtime": stats.st_mtime,
                                        "tracked": tracked,
                                        "ignored": ignored,
                                    }
                                )
                            except Exception:
                                continue

                            if len(pending_batch) >= BATCH_SIZE:
                                self._process_and_sync_batch(
                                    db, pending_batch, executor, now, job_id
                                )
                                pending_batch = []
                                if job_id is not None:
                                    JobManager.update_job(
                                        job_id,
                                        5.0,
                                        f"Indexing: {self.total_files_found} items discovered...",
                                    )

                if pending_batch:
                    self._process_and_sync_batch(
                        db, pending_batch, executor, now, job_id
                    )

            if job_id is not None and not JobManager.is_cancelled(job_id):
                db.commit()
                JobManager.complete_job(job_id)
                from app.services.notifications import notification_manager

                notification_manager.notify(
                    "Scan Completed",
                    f"Archive Command finished. {self.files_processed} items processed.",
                    "success",
                )

        except Exception as e:
            logger.exception(f"Scan failed: {e}")
            db.rollback()
            if job_id is not None:
                JobManager.fail_job(job_id, str(e))
        finally:
            self.is_running = False

    def _process_and_sync_batch(
        self, db: Session, batch: List[Dict[str, Any]], executor, now, job_id
    ):
        """Processes a batch: Consolidates all DB writes into the main thread's session"""
        paths = [f["path"] for f in batch]
        existing = {
            r.file_path: r
            for r in db.query(models.FilesystemState)
            .filter(models.FilesystemState.file_path.in_(paths))
            .all()
        }

        hashing_tasks = []

        for f in batch:
            ext = existing.get(f["path"])
            is_new = ext is None
            changed = (
                not ext
                or ext.size != f["size"]
                or ext.mtime != f["mtime"]
                or ext.is_ignored != f["ignored"]
            )

            # If it's a new file or changed, and we are tracking it, hash it!
            if (
                f["tracked"]
                and not f["ignored"]
                and (is_new or changed or not ext.sha256_hash)
            ):
                hashing_tasks.append(
                    executor.submit(self._hash_worker, f, is_new, job_id)
                )
            elif changed or is_new:
                # Metadata only sync
                if is_new:
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
                    ext.size = f["size"]
                    ext.mtime = f["mtime"]
                    ext.is_ignored = f["ignored"]
                    ext.last_seen_timestamp = now

            self.files_processed += 1

        db.flush()  # Send changes to SQLite buffer without final commit yet

        # Drain hashing results and write to DB using the main thread's session
        if hashing_tasks:
            for future in concurrent.futures.as_completed(hashing_tasks):
                res = future.result()
                if res:
                    f_path, f_hash, f_meta, f_is_new = res
                    if f_is_new:
                        db.add(
                            models.FilesystemState(
                                file_path=f_path,
                                size=f_meta["size"],
                                mtime=f_meta["mtime"],
                                sha256_hash=f_hash,
                                is_indexed=True,
                                is_ignored=f_meta["ignored"],
                                last_seen_timestamp=now,
                            )
                        )
                    else:
                        # Find object in the session cache if possible, or update by path
                        obj = existing.get(f_path)
                        if obj:
                            obj.sha256_hash = f_hash
                            obj.is_indexed = True
                            obj.last_seen_timestamp = now
                        else:
                            db.execute(
                                text(
                                    "UPDATE filesystem_state SET sha256_hash = :h, is_indexed = 1, last_seen_timestamp = :t WHERE file_path = :p"
                                ),
                                {"h": f_hash, "t": now, "p": f_path},
                            )

        db.commit()  # Single atomic commit per batch

    def _hash_worker(self, f_meta, is_new, job_id):
        """Pure worker: No database access here, just heavy CPU hashing"""
        h = self.compute_sha256(f_meta["path"], job_id)
        if not h:
            return None
        return f_meta["path"], h, f_meta, is_new


scanner_manager = ScannerService()
