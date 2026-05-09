import json
import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.schemas import ItemMetadataSchema, TreeNodeSchema
from app.api.common import escape_fts5_query
from app.db import models
from app.db.database import get_db

router = APIRouter(prefix="/archive", tags=["Archive Index"])


def get_source_roots(db_session: Session) -> List[str]:
    """Retrieves the list of configured root paths from system settings."""
    setting = (
        db_session.query(models.SystemSetting)
        .filter(models.SystemSetting.key == "source_roots")
        .first()
    )
    if not setting:
        # Fallback to scan_paths for legacy compatibility
        setting = (
            db_session.query(models.SystemSetting)
            .filter(models.SystemSetting.key == "scan_paths")
            .first()
        )
        if not setting:
            return []
    try:
        return json.loads(setting.value)
    except Exception:
        return [setting.value] if setting.value else []


@router.get("/browse", operation_id="archive_browse")
def browse(path: str = "ROOT", db_session: Session = Depends(get_db)):
    """Browses the archived file index at a specific path."""
    if path == "ROOT":
        # Root level: show source roots that have at least one protected file
        source_roots = get_source_roots(db_session)
        results = []
        for root in source_roots:
            # Check if this root contains ANY protected file
            # total: count files that are either not ignored OR already have a version
            # protected: count files that have a version
            prot_check = text("""
                SELECT
                    SUM(CASE WHEN fs.is_ignored = 0 OR EXISTS(SELECT 1 FROM file_versions fv2 WHERE fv2.filesystem_state_id = fs.id) THEN 1 ELSE 0 END) as total,
                    SUM(CASE WHEN EXISTS(SELECT 1 FROM file_versions fv WHERE fv.filesystem_state_id = fs.id) THEN 1 ELSE 0 END) as protected,
                    (SELECT GROUP_CONCAT(DISTINCT sm.identifier)
                     FROM file_versions fv
                     JOIN storage_media sm ON sm.id = fv.media_id
                     JOIN filesystem_state fs2 ON fs2.id = fv.filesystem_state_id
                     WHERE (fs2.file_path = :r OR fs2.file_path LIKE :prefix)) as media_list,
                    SUM(CASE WHEN EXISTS(SELECT 1 FROM restore_cart rc WHERE rc.filesystem_state_id = fs.id) THEN 1 ELSE 0 END) as selected_count,
                    SUM(fs.size) as total_size
                FROM filesystem_state fs
                WHERE (fs.file_path = :r OR fs.file_path LIKE :prefix)
            """)
            stats = db_session.execute(
                prot_check, {"r": root, "prefix": f"{root}/%"}
            ).fetchone()

            total = 0
            protected = 0
            media_list = []
            selected_count = 0
            total_size = 0
            if stats:
                total = stats[0] or 0
                protected = stats[1] or 0
                media_list = stats[2].split(",") if stats[2] else []
                selected_count = stats[3] or 0
                total_size = stats[4] or 0

            if protected > 0:
                results.append(
                    {
                        "name": root,
                        "path": root,
                        "type": "directory",
                        "size": total_size,
                        "vulnerable": (protected < total),
                        "selected": (
                            selected_count > 0 and selected_count == protected
                        ),
                        "indeterminate": (
                            selected_count > 0 and selected_count < protected
                        ),
                        "media": media_list,
                    }
                )
        return results

    query_path = path if path.endswith("/") else path + "/"

    # Find directories and their protection stats (Optimized: Single Pass)
    dir_sql = text("""
        SELECT
            SUBSTR(file_path, LENGTH(:prefix) + 1, INSTR(SUBSTR(file_path, LENGTH(:prefix) + 1), '/') - 1) as dir_name,
            SUM(CASE WHEN is_ignored = 0 OR EXISTS(SELECT 1 FROM file_versions fv3 WHERE fv3.filesystem_state_id = filesystem_state.id) THEN 1 ELSE 0 END) as total,
            SUM(CASE WHEN EXISTS(SELECT 1 FROM file_versions fv WHERE fv.filesystem_state_id = filesystem_state.id) THEN 1 ELSE 0 END) as protected,
            (SELECT GROUP_CONCAT(DISTINCT sm.identifier)
             FROM file_versions fv
             JOIN storage_media sm ON sm.id = fv.media_id
             JOIN filesystem_state fs2 ON fs2.id = fv.filesystem_state_id
             WHERE fs2.file_path LIKE :prefix || SUBSTR(file_path, LENGTH(:prefix) + 1, INSTR(SUBSTR(file_path, LENGTH(:prefix) + 1), '/') - 1) || '/%') as media_list,
            SUM(CASE WHEN EXISTS(SELECT 1 FROM restore_cart rc WHERE rc.filesystem_state_id = filesystem_state.id) THEN 1 ELSE 0 END) as selected_count,
            SUM(size) as total_size
        FROM filesystem_state
        WHERE file_path LIKE :prefix_wildcard
        AND file_path != :prefix
        AND INSTR(SUBSTR(file_path, LENGTH(:prefix) + 1), '/') > 0
        GROUP BY dir_name
    """)
    dirs = db_session.execute(
        dir_sql, {"prefix": query_path, "prefix_wildcard": f"{query_path}%"}
    ).fetchall()

    # Find files (immediate children) with their media locations and archive coverage
    file_sql = text("""
        SELECT
            fs.id, fs.file_path, fs.size, fs.mtime,
            EXISTS(SELECT 1 FROM file_versions fv WHERE fv.filesystem_state_id = fs.id) as has_version,
            (SELECT GROUP_CONCAT(sm.identifier)
             FROM file_versions fv
             JOIN storage_media sm ON sm.id = fv.media_id
             WHERE fv.filesystem_state_id = fs.id) as media_list,
            EXISTS(SELECT 1 FROM restore_cart rc WHERE rc.filesystem_state_id = fs.id) as is_selected,
            COALESCE((SELECT SUM(fv.offset_end - fv.offset_start)
                      FROM file_versions fv
                      WHERE fv.filesystem_state_id = fs.id), 0) as archived_bytes
        FROM filesystem_state fs
        WHERE fs.file_path LIKE :prefix_wildcard
        AND fs.file_path != :prefix
        AND INSTR(SUBSTR(fs.file_path, LENGTH(:prefix) + 1), '/') = 0
    """)
    files = db_session.execute(
        file_sql, {"prefix": query_path, "prefix_wildcard": f"{query_path}%"}
    ).fetchall()

    results = []

    for d in dirs:
        if not d[0] or d[0] == "/":
            continue

        total = d[1] or 0
        protected = d[2] or 0
        media_list = d[3].split(",") if d[3] else []
        selected_count = d[4] or 0
        total_size = d[5] or 0

        # Only show directories that have at least one protected file
        if protected == 0:
            continue

        full_dir_path = query_path + d[0]
        results.append(
            {
                "name": d[0],
                "path": full_dir_path,
                "type": "directory",
                "size": total_size,
                "vulnerable": (protected < total),
                "selected": (selected_count > 0 and selected_count == protected),
                "indeterminate": (selected_count > 0 and selected_count < protected),
                "media": media_list,
            }
        )

    for f in files:
        # Only show files that actually have at least one version on media
        if not f[4]:  # f[4] is has_version
            continue

        archived_bytes = f[7] or 0
        file_size = f[2] or 0
        is_partially_archived = archived_bytes < file_size

        results.append(
            {
                "name": os.path.basename(f[1]),
                "path": f[1],
                "type": "file",
                "size": f[2],
                "mtime": datetime.fromtimestamp(f[3], tz=timezone.utc),
                "vulnerable": False,
                "selected": bool(f[6]),
                "media": f[5].split(",") if f[5] else [],
                "is_partially_archived": is_partially_archived,
                "archived_bytes": archived_bytes,
            }
        )

    # Deduplicate by path to prevent frontend keyed each block errors
    seen_paths: set[str] = set()
    deduped_results: list[dict] = []
    for r in results:
        if r["path"] not in seen_paths:
            seen_paths.add(r["path"])
            deduped_results.append(r)
    results = deduped_results

    return results


@router.get("/search", operation_id="archive_search")
def search(q: str, path: Optional[str] = None, db_session: Session = Depends(get_db)):
    """Performs FTS5 search across archived files, optionally scoped by path."""
    if not q or len(q) < 3:
        return []

    search_sql = text(
        """
        SELECT
            fs.id, fs.file_path, fs.size, fs.mtime,
            EXISTS(SELECT 1 FROM file_versions fv WHERE fv.filesystem_state_id = fs.id) as has_version,
            (SELECT GROUP_CONCAT(sm.identifier)
             FROM file_versions fv
             JOIN storage_media sm ON sm.id = fv.media_id
             WHERE fv.filesystem_state_id = fs.id) as media_list,
            EXISTS(SELECT 1 FROM restore_cart rc WHERE rc.filesystem_state_id = fs.id) as is_selected,
            COALESCE((SELECT SUM(fv.offset_end - fv.offset_start)
                      FROM file_versions fv
                      WHERE fv.filesystem_state_id = fs.id), 0) as archived_bytes
        FROM filesystem_fts fts
        JOIN filesystem_state fs ON fs.id = fts.rowid
        WHERE filesystem_fts MATCH :query
          AND fs.file_path LIKE :path_prefix
        ORDER BY rank
        LIMIT 100
    """
    )

    path_prefix = f"{path}%" if path and path != "ROOT" else "%"
    query_params = {"query": escape_fts5_query(q), "path_prefix": path_prefix}

    rows = db_session.execute(search_sql, query_params).fetchall()
    results = []
    for r in rows:
        if not r[4]:  # Only show if has_version is True
            continue
        archived_bytes = r[7] or 0
        file_size = r[2] or 0
        is_partially_archived = archived_bytes < file_size
        results.append(
            {
                "name": os.path.basename(r[1]),
                "path": r[1],
                "type": "file",
                "size": r[2],
                "mtime": datetime.fromtimestamp(r[3], tz=timezone.utc),
                "vulnerable": False,
                "selected": bool(r[6]),
                "media": r[5].split(",") if r[5] else [],
                "is_partially_archived": is_partially_archived,
                "archived_bytes": archived_bytes,
            }
        )
    return results


@router.get("/tree", response_model=List[TreeNodeSchema], operation_id="archive_tree")
def tree(path: Optional[str] = None, db_session: Session = Depends(get_db)):
    """Returns a recursive tree view of the virtual archive index."""
    if path is None or path == "ROOT":
        # Root level: show source roots that have at least one protected file
        source_roots = get_source_roots(db_session)
        results = []
        for root in source_roots:
            # Check if this root contains ANY protected file
            prot_check = text("""
                SELECT 1 FROM filesystem_state fs
                WHERE (fs.file_path = :r OR fs.file_path LIKE :prefix)
                AND EXISTS(SELECT 1 FROM file_versions fv WHERE fv.filesystem_state_id = fs.id)
                LIMIT 1
            """)
            has_prot = db_session.execute(
                prot_check, {"r": root, "prefix": f"{root}/%"}
            ).fetchone()
            if has_prot:
                results.append(TreeNodeSchema(name=root, path=root, has_children=True))
        return results

    query_path = path if path.endswith("/") else path + "/"

    # Find subdirectories that contain at least one protected file (ignoring current is_ignored state)
    dir_sql = text("""
        SELECT DISTINCT
            SUBSTR(file_path, LENGTH(:prefix) + 1, INSTR(SUBSTR(file_path, LENGTH(:prefix) + 1), '/') - 1) as dir_name
        FROM filesystem_state fs
        WHERE file_path LIKE :prefix_wildcard
        AND file_path != :prefix
        AND INSTR(SUBSTR(file_path, LENGTH(:prefix) + 1), '/') > 0
        AND EXISTS(SELECT 1 FROM file_versions fv WHERE fv.filesystem_state_id = fs.id)
    """)

    path_prefix = query_path
    dirs = db_session.execute(
        dir_sql, {"prefix": path_prefix, "prefix_wildcard": f"{path_prefix}%"}
    ).fetchall()

    results = []
    for d in dirs:
        if not d[0] or d[0] == "/":
            continue
        results.append(
            TreeNodeSchema(name=d[0], path=query_path + d[0], has_children=True)
        )

    results.sort(key=lambda x: x.name.lower())
    return results


@router.get(
    "/metadata", response_model=ItemMetadataSchema, operation_id="archive_metadata"
)
def metadata(path: str, db_session: Session = Depends(get_db)):
    """Retrieves full version history and location details for an indexed file or directory."""
    item = (
        db_session.query(models.FilesystemState)
        .filter(models.FilesystemState.file_path == path)
        .first()
    )

    if item:
        # Exact file match
        versions = []
        for v in item.versions:
            versions.append(
                {
                    "media_id": v.media.identifier,
                    "media_type": v.media.media_type,
                    "archive_id": v.file_number,
                    "created_at": v.created_at,
                    "is_split": v.is_split,
                    "offset": v.offset_start,
                }
            )

        archived_bytes = sum((v.offset_end - v.offset_start) for v in item.versions)
        is_partially_archived = archived_bytes > 0 and archived_bytes < item.size

        return ItemMetadataSchema(
            id=item.id,
            path=item.file_path,
            type="file",
            size=item.size,
            mtime=datetime.fromtimestamp(item.mtime, tz=timezone.utc),
            last_seen_timestamp=item.last_seen_timestamp,
            sha256_hash=item.sha256_hash,
            is_ignored=item.is_ignored,
            versions=versions,
            is_partially_archived=is_partially_archived,
            archived_bytes=archived_bytes,
        )

    # No exact match — check if this is a directory with archived children
    prefix = path if path.endswith("/") else path + "/"
    dir_stats = db_session.execute(
        text("""
            SELECT
                COUNT(*) as child_count,
                SUM(size) as total_size,
                MAX(mtime) as latest_mtime,
                MAX(last_seen_timestamp) as latest_seen
            FROM filesystem_state
            WHERE file_path LIKE :prefix
        """),
        {"prefix": f"{prefix}%"},
    ).fetchone()

    if not dir_stats or dir_stats[0] == 0:
        raise HTTPException(status_code=404, detail="File not found in index.")

    # Aggregate unique media locations for all children
    media_rows = db_session.execute(
        text("""
            SELECT DISTINCT
                sm.identifier as media_id,
                sm.media_type,
                MIN(fv.created_at) as earliest_created
            FROM file_versions fv
            JOIN storage_media sm ON sm.id = fv.media_id
            JOIN filesystem_state fs ON fs.id = fv.filesystem_state_id
            WHERE fs.file_path LIKE :prefix
            GROUP BY sm.identifier, sm.media_type
        """),
        {"prefix": f"{prefix}%"},
    ).fetchall()

    versions = []
    for row in media_rows:
        versions.append(
            {
                "media_id": row[0],
                "media_type": row[1],
                "archive_id": "—",
                "created_at": row[2],
                "is_split": False,
                "offset": 0,
            }
        )

    return ItemMetadataSchema(
        id=-1,
        path=path,
        type="directory",
        size=dir_stats[1] or 0,
        mtime=datetime.fromtimestamp(dir_stats[2] or 0, tz=timezone.utc),
        last_seen_timestamp=dir_stats[3],
        child_count=dir_stats[0],
        versions=versions,
    )
