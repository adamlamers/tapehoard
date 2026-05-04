from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.api.common import (
    FileItemSchema,
    BrowseResponseSchema,
    get_source_roots,
    get_exclusion_spec,
    get_ignored_status,
    _validate_path_within_roots,
    _get_last_scan_time,
)
from sqlalchemy import text
from app.db import models
import os

router = APIRouter(tags=["System"])


@router.get(
    "/browse", response_model=BrowseResponseSchema, operation_id="filesystem_browse"
)
def browse_system_path(
    path: Optional[str] = None, db_session: Session = Depends(get_db)
):
    """Provides a browsable view of the indexed filesystem from the database."""
    roots = get_source_roots(db_session)
    tracking_rules = db_session.query(models.TrackedSource).all()
    tracking_map = {rule.path: rule.action for rule in tracking_rules}
    exclusion_spec = get_exclusion_spec(db_session)
    last_scan_time = _get_last_scan_time(db_session)

    if path is None or path == "ROOT":
        results = []
        for root_path in roots:
            is_ignored = get_ignored_status(root_path, tracking_map, exclusion_spec)
            results.append(
                FileItemSchema(
                    name=root_path,
                    path=root_path,
                    type="directory",
                    ignored=is_ignored,
                )
            )
        return BrowseResponseSchema(files=results, last_scan_time=last_scan_time)

    if not _validate_path_within_roots(path, roots):
        raise HTTPException(
            status_code=403, detail="Path is outside configured source roots"
        )

    target_prefix = path if path.endswith("/") else path + "/"

    # Escape LIKE wildcards in the prefix
    escaped_prefix = (
        target_prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )

    files_sql = text("""
        SELECT file_path, size, mtime, sha256_hash, is_ignored
        FROM filesystem_state
        WHERE file_path LIKE :prefix ESCAPE '\\'
        AND file_path != :prefix
    """)
    rows = db_session.execute(files_sql, {"prefix": f"{escaped_prefix}%"}).fetchall()

    if not rows and os.path.isdir(path):
        try:
            live_results = []
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        if entry.name.startswith("."):
                            continue
                        entry_path = entry.path
                        is_dir = entry.is_dir()
                        is_ignored = get_ignored_status(
                            entry_path, tracking_map, exclusion_spec
                        )
                        if is_dir:
                            live_results.append(
                                FileItemSchema(
                                    name=entry.name,
                                    path=entry_path,
                                    type="directory",
                                    ignored=is_ignored,
                                )
                            )
                        else:
                            stat = entry.stat()
                            live_results.append(
                                FileItemSchema(
                                    name=entry.name,
                                    path=entry_path,
                                    type="file",
                                    size=stat.st_size,
                                    mtime=stat.st_mtime,
                                    ignored=is_ignored,
                                    sha256_hash=None,
                                )
                            )
                    except OSError:
                        continue
            live_results.sort(key=lambda x: (x.type != "directory", x.name.lower()))
            return BrowseResponseSchema(
                files=live_results, last_scan_time=last_scan_time
            )
        except OSError:
            pass

    # Aggregate sizes for directories from indexed rows
    dir_sizes: dict[str, int] = {}
    for file_path, size, _mtime, _sha256_hash, _is_ignored in rows:
        relative = file_path[len(target_prefix) :]
        if "/" in relative:
            immediate_name = relative.split("/")[0]
            child_path = target_prefix + immediate_name
            dir_sizes[child_path] = dir_sizes.get(child_path, 0) + (size or 0)

    results = []
    seen = set()

    for file_path, size, mtime, sha256_hash, is_ignored in rows:
        relative = file_path[len(target_prefix) :]
        if "/" in relative:
            immediate_name = relative.split("/")[0]
            child_path = target_prefix + immediate_name
            if child_path not in seen:
                seen.add(child_path)
                dir_ignored = get_ignored_status(
                    child_path, tracking_map, exclusion_spec
                )
                results.append(
                    FileItemSchema(
                        name=immediate_name,
                        path=child_path,
                        type="directory",
                        size=dir_sizes.get(child_path, 0),
                        ignored=dir_ignored,
                    )
                )
        else:
            if file_path not in seen:
                seen.add(file_path)
                results.append(
                    FileItemSchema(
                        name=relative,
                        path=file_path,
                        type="file",
                        size=size,
                        mtime=mtime,
                        ignored=is_ignored,
                        sha256_hash=sha256_hash,
                    )
                )

    results.sort(key=lambda x: (x.type != "directory", x.name.lower()))
    return BrowseResponseSchema(files=results, last_scan_time=last_scan_time)


@router.get(
    "/search", response_model=List[FileItemSchema], operation_id="filesystem_search"
)
def search_system_index(
    q: str,
    path: Optional[str] = None,
    include_ignored: bool = False,
    db_session: Session = Depends(get_db),
):
    """Instantaneous full-text search across the entire indexed filesystem, optionally scoped by path."""
    if not q or len(q) < 3:
        return []

    ignore_filter = " AND fs.is_ignored = 0" if not include_ignored else ""
    path_filter = ""
    query_params = {"query": f'"{q}"'}

    if path and path != "ROOT":
        path_filter = " AND fs.file_path LIKE :path_prefix"
        query_params["path_prefix"] = f"{path}%"

    search_sql = text(
        f"""
        SELECT fs.file_path, fs.size, fs.mtime, fs.id, fs.is_ignored, fs.sha256_hash
        FROM filesystem_fts
        JOIN filesystem_state fs ON fs.id = filesystem_fts.rowid
        WHERE filesystem_fts MATCH :query {ignore_filter} {path_filter}
        AND fs.sha256_hash IS NOT NULL
        LIMIT 200
    """
    )

    files = db_session.execute(search_sql, query_params).fetchall()

    results = []
    for file_record in files:
        full_path = file_record[0]
        # Trust the indexed ignore state from the DB
        db_ignored = bool(file_record[4])

        results.append(
            FileItemSchema(
                name=full_path.split("/")[-1],
                path=full_path,
                type="file",
                size=file_record[1],
                mtime=file_record[2],
                ignored=db_ignored,
                sha256_hash=file_record[5],
            )
        )

    results.sort(key=lambda x: x.name.lower())
    return results
