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
    escape_fts5_query,
)
from sqlalchemy import text
from app.db import models

router = APIRouter(tags=["System"])


@router.get(
    "/browse", response_model=BrowseResponseSchema, operation_id="filesystem_browse"
)
def browse_system_path(
    path: Optional[str] = None, db_session: Session = Depends(get_db)
):
    """Provides a browsable view of the indexed filesystem from the database.

    Operates exclusively on the database index (index-only principle).
    Never falls back to the live filesystem.
    """
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

    # --- Files directly under this path (non-recursive) ---
    file_sql = text("""
        SELECT file_path, size, mtime, sha256_hash, is_ignored
        FROM filesystem_state
        WHERE file_path LIKE :prefix_wildcard ESCAPE '\\'
          AND file_path NOT LIKE :prefix_nested ESCAPE '\\'
          AND file_path != :prefix
    """)
    file_rows = db_session.execute(
        file_sql,
        {
            "prefix": target_prefix,
            "prefix_wildcard": f"{escaped_prefix}%",
            "prefix_nested": f"{escaped_prefix}%/%",
        },
    ).fetchall()

    results: list[FileItemSchema] = []
    seen: set[str] = set()

    for file_path, size, mtime, sha256_hash, is_ignored in file_rows:
        if file_path not in seen:
            seen.add(file_path)
            results.append(
                FileItemSchema(
                    name=file_path.split("/")[-1],
                    path=file_path,
                    type="file",
                    size=size,
                    mtime=mtime,
                    ignored=is_ignored,
                    sha256_hash=sha256_hash,
                )
            )

    # --- Directories under this path (aggregated via GROUP BY) ---
    dir_sql = text("""
        SELECT
            SUBSTR(file_path, LENGTH(:prefix) + 1,
                   INSTR(SUBSTR(file_path, LENGTH(:prefix) + 1), '/') - 1) as dir_name,
            SUM(size) as total_size
        FROM filesystem_state
        WHERE file_path LIKE :prefix_wildcard ESCAPE '\\'
          AND file_path != :prefix
          AND INSTR(SUBSTR(file_path, LENGTH(:prefix) + 1), '/') > 0
        GROUP BY dir_name
    """)
    dir_rows = db_session.execute(
        dir_sql,
        {
            "prefix": target_prefix,
            "prefix_wildcard": f"{escaped_prefix}%",
        },
    ).fetchall()

    for dir_name, total_size in dir_rows:
        if not dir_name or dir_name == "/":
            continue
        child_path = target_prefix + dir_name
        if child_path not in seen:
            seen.add(child_path)
            dir_ignored = get_ignored_status(
                child_path + "/", tracking_map, exclusion_spec
            )
            results.append(
                FileItemSchema(
                    name=dir_name,
                    path=child_path,
                    type="directory",
                    size=total_size or 0,
                    ignored=dir_ignored,
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
    query_params = {"query": escape_fts5_query(q)}

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
