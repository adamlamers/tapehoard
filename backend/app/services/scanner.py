import os
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple, Any, cast
from loguru import logger
from sqlalchemy.orm import Session
from app.db import models
from app.db.database import SessionLocal
import concurrent.futures
import pathspec
import json


class JobManager:
    # Set of job IDs that have been requested to cancel
    _cancelled_jobs: Set[int] = set()

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
            if job_id in JobManager._cancelled_jobs:
                JobManager._cancelled_jobs.remove(job_id)
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
            if job_id in JobManager._cancelled_jobs:
                JobManager._cancelled_jobs.remove(job_id)
        finally:
            db.close()

    @staticmethod
    def cancel_job(job_id: int):
        JobManager._cancelled_jobs.add(job_id)
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
        return job_id in JobManager._cancelled_jobs


class ScannerService:
    def __init__(self):
        self.is_running = False
        self.last_run_time: Optional[datetime] = None
        self.files_processed = 0
        self.files_hashed = 0
        self.total_files_found = 0
        self.current_path = ""

    def compute_sha256(self, file_path: str, job_id: Optional[int] = None) -> str:
        sha256_hash = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(1048576), b""):
                    # Check for cancellation during block read
                    if job_id is not None and JobManager.is_cancelled(job_id):
                        return ""
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
        local_source = os.path.abspath(os.path.join(os.getcwd(), "..", "source_data"))
        if os.path.exists(local_source):
            return [local_source]
        return ["/source_data"]

    def scan_sources(self, db: Session, job_id: Optional[int] = None):
        if self.is_running:
            logger.warning("Scan already in progress")
            return

        self.is_running = True
        self.files_processed = 0
        self.files_hashed = 0
        self.total_files_found = 0

        if job_id is not None:
            JobManager.start_job(job_id)

        try:
            # 1. Load Rules & Roots
            spec = self._get_exclusion_spec(db)
            roots = self._get_source_roots(db)
            tracking_rules = db.query(models.TrackedSource).all()

            # Type-safe list extraction to help 'ty' inference
            raw_include: List[str] = [
                r.path for r in tracking_rules if r.action == "include"
            ]
            raw_exclude: List[str] = [
                r.path for r in tracking_rules if r.action == "exclude"
            ]

            # Using cast because ty incorrectly infers result of sorted(List[str], key=len) as List[Sized]
            include_rules = cast(List[str], sorted(raw_include, key=len, reverse=True))
            exclude_rules = cast(List[str], sorted(raw_exclude, key=len, reverse=True))

            def get_tracking_status(path: str) -> Tuple[bool, bool]:
                # returns (is_tracked, is_ignored)
                is_ignored = False
                if spec and spec.match_file(path):
                    is_ignored = True

                # Check explicit rules
                # If a rule matches, it determines the tracking state
                for ex in exclude_rules:
                    if path == ex or path.startswith(ex + "/"):
                        # Now check if there's a more specific include under this exclude
                        for inc in include_rules:
                            if len(inc) > len(ex) and (
                                path == inc or path.startswith(inc + "/")
                            ):
                                return True, is_ignored
                        return False, is_ignored

                for inc in include_rules:
                    if path == inc or path.startswith(inc + "/"):
                        return True, is_ignored

                # NEW DEFAULT: If no explicit rule and NOT globally ignored, track it!
                return not is_ignored, is_ignored

            if job_id is not None:
                JobManager.update_job(job_id, 2.0, "Initiating metadata discovery...")

            # 2. Optimized Discovery & Sync Phase
            BATCH_SIZE = 1000
            pending_files: List[Dict[str, Any]] = []
            now = datetime.now(timezone.utc)

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=os.cpu_count()
            ) as executor:
                hashing_futures: List[concurrent.futures.Future] = []

                for root_path in roots:
                    if job_id is not None and JobManager.is_cancelled(job_id):
                        break
                    if not os.path.exists(root_path):
                        continue
                    for root, dirs, files in os.walk(root_path):
                        if job_id is not None and JobManager.is_cancelled(job_id):
                            break

                        original_dirs = list(dirs)
                        for d in original_dirs:
                            d_path = os.path.join(root, d)
                            if spec and spec.match_file(d_path + "/"):
                                dirs.remove(d)

                        for file in files:
                            if job_id is not None and JobManager.is_cancelled(job_id):
                                break
                            full_path = os.path.join(root, file)
                            try:
                                stats = os.stat(full_path)
                                tracked, ignored = get_tracking_status(full_path)
                                pending_files.append(
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

                            if len(pending_files) >= BATCH_SIZE:
                                self._sync_batch(
                                    db,
                                    pending_files,
                                    executor,
                                    hashing_futures,
                                    now,
                                    job_id,
                                )
                                pending_files = []

                if job_id is not None and JobManager.is_cancelled(job_id):
                    logger.info("Scan task detected cancellation. Stopping.")
                    return

                if pending_files:
                    self._sync_batch(
                        db, pending_files, executor, hashing_futures, now, job_id
                    )

                if hashing_futures:
                    if job_id is not None:
                        JobManager.update_job(
                            job_id,
                            50.0,
                            f"Processing {len(hashing_futures)} hashing tasks...",
                        )

                    for future in concurrent.futures.as_completed(hashing_futures):
                        if job_id is not None and JobManager.is_cancelled(job_id):
                            break
                        result = future.result()
                        if result:
                            f_path, f_size, f_mtime, f_hash, f_ignored, f_new = result
                            if (
                                f_hash == ""
                                and job_id is not None
                                and JobManager.is_cancelled(job_id)
                            ):
                                continue  # Cancelled during hash

                            ext = (
                                db.query(models.FilesystemState)
                                .filter(models.FilesystemState.file_path == f_path)
                                .first()
                            )
                            if f_new and not ext:
                                db.add(
                                    models.FilesystemState(
                                        file_path=f_path,
                                        size=f_size,
                                        mtime=f_mtime,
                                        sha256_hash=f_hash,
                                        is_indexed=f_hash is not None,
                                        is_ignored=f_ignored,
                                        last_seen_timestamp=now,
                                    )
                                )
                            elif ext:
                                ext.size = f_size
                                ext.mtime = f_mtime
                                ext.sha256_hash = f_hash
                                ext.is_indexed = f_hash is not None
                                ext.is_ignored = f_ignored
                                ext.last_seen_timestamp = now

                            if f_hash:
                                self.files_hashed += 1
                            self.files_processed += 1
                            if self.files_processed % 50 == 0:
                                db.commit()
                                if job_id is not None:
                                    if self.total_files_found > 0:
                                        prog = 10.0 + (
                                            90.0
                                            * (
                                                self.files_processed
                                                / self.total_files_found
                                            )
                                        )
                                        status_text = f"Indexing: {self.files_processed}/{self.total_files_found} items"
                                    else:
                                        prog = (
                                            10.0  # Keep it at a steady "working" phase
                                        )
                                        status_text = f"Scanning: {self.files_processed} items discovered..."

                                    JobManager.update_job(
                                        job_id, round(prog, 1), status_text
                                    )

            if job_id is not None and JobManager.is_cancelled(job_id):
                return

            db.commit()
            self.last_run_time = datetime.now(timezone.utc)
            if job_id is not None:
                JobManager.complete_job(job_id)
                from app.services.notifications import notification_manager

                notification_manager.notify(
                    "Scan Completed",
                    f"System scan finished. {self.files_processed} files processed, {self.files_hashed} new hashes computed.",
                    "success",
                )

        except Exception as e:
            logger.exception(f"Scan failed: {e}")
            db.rollback()
            if job_id is not None:
                JobManager.fail_job(job_id, str(e))
                from app.services.notifications import notification_manager

                notification_manager.notify(
                    "Scan Failed", f"System scan failed: {str(e)}", "failure"
                )
        finally:
            self.is_running = False
            self.current_path = ""

    def _sync_batch(
        self, db: Session, files: List[Dict[str, Any]], executor, futures, now, job_id
    ):
        if job_id is not None and JobManager.is_cancelled(job_id):
            return

        paths = [f["path"] for f in files]
        existing_records = {
            r.file_path: r
            for r in db.query(models.FilesystemState)
            .filter(models.FilesystemState.file_path.in_(paths))
            .all()
        }

        for f in files:
            if job_id is not None and JobManager.is_cancelled(job_id):
                return
            self.current_path = f["path"]
            ext = existing_records.get(f["path"])

            needs_metadata_update = (
                not ext
                or ext.size != f["size"]
                or ext.mtime != f["mtime"]
                or ext.is_ignored != f["ignored"]
            )
            # We hash if tracked AND NOT ignored
            needs_hashing = (
                f["tracked"]
                and not f["ignored"]
                and (not ext or not ext.sha256_hash or needs_metadata_update)
            )

            if needs_hashing:
                futures.append(
                    executor.submit(
                        self._process_file,
                        f["path"],
                        f["size"],
                        f["mtime"],
                        f["tracked"],
                        f["ignored"],
                        True,
                        ext is None,
                        job_id,
                    )
                )
            elif needs_metadata_update or ext:
                if not ext:
                    db.add(
                        models.FilesystemState(
                            file_path=f["path"],
                            size=f["size"],
                            mtime=f["mtime"],
                            sha256_hash=None,
                            is_indexed=False,
                            is_ignored=f["ignored"],
                            last_seen_timestamp=now,
                        )
                    )
                else:
                    ext.size = f["size"]
                    ext.mtime = f["mtime"]
                    ext.is_ignored = f["ignored"]
                    ext.is_indexed = ext.sha256_hash is not None
                    ext.last_seen_timestamp = now
                self.files_processed += 1

        db.commit()
        if job_id is not None:
            JobManager.update_job(
                job_id, 10.0, f"Discovered and synced {self.files_processed} items..."
            )

    def _process_file(
        self,
        file_path: str,
        size: int,
        mtime: float,
        tracked: bool,
        ignored: bool,
        hash_it: bool,
        is_new: bool,
        job_id: Optional[int] = None,
    ):
        if job_id is not None and JobManager.is_cancelled(job_id):
            return (file_path, size, mtime, "", ignored, is_new)
        sha_hash = self.compute_sha256(file_path, job_id) if hash_it else None
        return (file_path, size, mtime, sha_hash, ignored, is_new)


scanner_manager = ScannerService()
