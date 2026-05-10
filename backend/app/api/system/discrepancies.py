from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.api.schemas import BatchDiscrepancyAction, DiscrepancySchema, TreeNodeSchema
from app.db import models
from datetime import datetime, timezone
import os

router = APIRouter(tags=["System"])


@router.get(
    "/discrepancies",
    response_model=List[DiscrepancySchema],
    operation_id="list_discrepancies",
)
def list_discrepancies(db_session: Session = Depends(get_db)):
    """Lists files with discrepancies: confirmed deleted or unhashed and missing from disk."""
    deleted_records = (
        db_session.query(models.FilesystemState)
        .filter(
            models.FilesystemState.is_deleted.is_(True),
            models.FilesystemState.is_ignored.is_(False),
            models.FilesystemState.missing_acknowledged_at.is_(None),
        )
        .order_by(models.FilesystemState.last_seen_timestamp.desc())
        .all()
    )

    unhashed_missing = (
        db_session.query(models.FilesystemState)
        .filter(
            models.FilesystemState.sha256_hash.is_(None),
            models.FilesystemState.is_ignored.is_(False),
            models.FilesystemState.is_deleted.is_(False),
            models.FilesystemState.missing_acknowledged_at.is_(None),
        )
        .all()
    )

    # Batch-load valid version flags to avoid N+1 (MEDIUM #14)
    all_records = deleted_records + unhashed_missing
    record_ids = {r.id for r in all_records}
    if record_ids:
        valid_version_rows = (
            db_session.query(models.FileVersion.filesystem_state_id)
            .join(models.StorageMedia)
            .filter(
                models.FileVersion.filesystem_state_id.in_(record_ids),
                models.StorageMedia.status.in_(["active", "full", "offline"]),
            )
            .distinct()
            .all()
        )
        ids_with_valid_versions = {row[0] for row in valid_version_rows}
    else:
        ids_with_valid_versions = set()

    results = []
    seen_ids = set()
    for record in all_records:
        if record.id in seen_ids:
            continue
        seen_ids.add(record.id)

        has_valid_versions = record.id in ids_with_valid_versions

        if record.is_deleted:
            results.append(
                DiscrepancySchema(
                    id=record.id,
                    path=record.file_path,
                    size=record.size,
                    mtime=datetime.fromtimestamp(record.mtime, tz=timezone.utc),
                    last_seen_timestamp=record.last_seen_timestamp,
                    sha256_hash=record.sha256_hash,
                    is_deleted=True,
                    has_versions=has_valid_versions,
                )
            )
        elif not os.path.exists(record.file_path):
            results.append(
                DiscrepancySchema(
                    id=record.id,
                    path=record.file_path,
                    size=record.size,
                    mtime=datetime.fromtimestamp(record.mtime, tz=timezone.utc),
                    last_seen_timestamp=record.last_seen_timestamp,
                    sha256_hash=record.sha256_hash,
                    is_deleted=False,
                    has_versions=has_valid_versions,
                )
            )

    return results


def _resolve_ids_from_action(
    action: BatchDiscrepancyAction, db_session: Session
) -> List[int]:
    if action.ids:
        return action.ids
    if action.path_prefix:
        prefix = action.path_prefix
        if not prefix.endswith("/"):
            # If there are files under this path in the index, treat it as a directory
            has_children = (
                db_session.query(models.FilesystemState)
                .filter(models.FilesystemState.file_path.startswith(prefix + "/"))
                .first()
                is not None
            )
            if has_children:
                prefix += "/"

        records = (
            db_session.query(models.FilesystemState)
            .filter(models.FilesystemState.file_path.startswith(prefix))
            .all()
        )
        return [r.id for r in records]
    return []


@router.post("/discrepancies/batch/confirm", operation_id="batch_confirm_discrepancies")
def batch_confirm_discrepancies(
    action: BatchDiscrepancyAction, db_session: Session = Depends(get_db)
):
    ids = _resolve_ids_from_action(action, db_session)
    if not ids:
        raise HTTPException(status_code=400, detail="No IDs or path prefix provided")
    db_session.query(models.FilesystemState).filter(
        models.FilesystemState.id.in_(ids)
    ).update({models.FilesystemState.is_deleted: True}, synchronize_session="fetch")
    db_session.commit()
    return {
        "message": f"{len(ids)} file(s) marked as confirmed deleted",
        "count": len(ids),
    }


@router.post("/discrepancies/batch/dismiss", operation_id="batch_dismiss_discrepancies")
def batch_dismiss_discrepancies(
    action: BatchDiscrepancyAction, db_session: Session = Depends(get_db)
):
    ids = _resolve_ids_from_action(action, db_session)
    if not ids:
        raise HTTPException(status_code=400, detail="No IDs or path prefix provided")
    db_session.query(models.FilesystemState).filter(
        models.FilesystemState.id.in_(ids)
    ).update(
        {
            models.FilesystemState.missing_acknowledged_at: datetime.now(timezone.utc),
        },
        synchronize_session="fetch",
    )
    db_session.commit()
    return {"message": f"{len(ids)} discrepancy(ies) dismissed", "count": len(ids)}


@router.post("/discrepancies/batch/delete", operation_id="batch_delete_discrepancies")
def batch_delete_discrepancies(
    action: BatchDiscrepancyAction, db_session: Session = Depends(get_db)
):
    ids = _resolve_ids_from_action(action, db_session)
    if not ids:
        raise HTTPException(status_code=400, detail="No IDs or path prefix provided")
    db_session.query(models.RestoreCart).filter(
        models.RestoreCart.filesystem_state_id.in_(ids)
    ).delete(synchronize_session="fetch")
    db_session.query(models.FileVersion).filter(
        models.FileVersion.filesystem_state_id.in_(ids)
    ).delete(synchronize_session="fetch")
    db_session.query(models.FilesystemState).filter(
        models.FilesystemState.id.in_(ids)
    ).delete(synchronize_session="fetch")
    db_session.commit()
    return {"message": f"{len(ids)} record(s) permanently deleted", "count": len(ids)}


class BatchResolveReport(BaseModel):
    recovered_count: int
    lost_count: int
    recovered_paths: List[str]
    lost_paths: List[str]
    message: str


@router.post(
    "/discrepancies/batch/resolve",
    response_model=BatchResolveReport,
    operation_id="batch_resolve_discrepancies",
)
def batch_resolve_discrepancies(
    action: BatchDiscrepancyAction, db_session: Session = Depends(get_db)
):
    """Smart batch action: add files with backups to restore queue, confirm deletion for files without backups."""
    ids = _resolve_ids_from_action(action, db_session)
    if not ids:
        raise HTTPException(status_code=400, detail="No IDs or path prefix provided")

    records = (
        db_session.query(models.FilesystemState)
        .filter(models.FilesystemState.id.in_(ids))
        .all()
    )

    recoverable = [r for r in records if r.versions]
    lost = [r for r in records if not r.versions]

    # Add recoverable files to restore queue
    now = datetime.now(timezone.utc)
    for r in recoverable:
        existing = (
            db_session.query(models.RestoreCart)
            .filter(models.RestoreCart.filesystem_state_id == r.id)
            .first()
        )
        if not existing:
            db_session.add(models.RestoreCart(filesystem_state_id=r.id, created_at=now))

    # Mark lost files as confirmed deleted and dismiss from discrepancies
    lost_ids = [r.id for r in lost]
    if lost_ids:
        db_session.query(models.FilesystemState).filter(
            models.FilesystemState.id.in_(lost_ids)
        ).update(
            {
                models.FilesystemState.is_deleted: True,
                models.FilesystemState.missing_acknowledged_at: datetime.now(
                    timezone.utc
                ),
            },
            synchronize_session="fetch",
        )

    db_session.commit()

    return BatchResolveReport(
        recovered_count=len(recoverable),
        lost_count=len(lost),
        recovered_paths=[r.file_path for r in recoverable],
        lost_paths=[r.file_path for r in lost],
        message=f"{len(recoverable)} file(s) queued for recovery, {len(lost)} file(s) confirmed as permanently lost",
    )


@router.post("/discrepancies/{file_id}/confirm", operation_id="confirm_discrepancy")
def confirm_discrepancy(file_id: int, db_session: Session = Depends(get_db)):
    """Marks a file as confirmed deleted (soft delete)."""
    record = db_session.get(models.FilesystemState, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File record not found")
    record.is_deleted = True
    db_session.commit()
    return {"message": f"File '{record.file_path}' marked as deleted"}


@router.post("/discrepancies/{file_id}/dismiss", operation_id="dismiss_discrepancy")
def dismiss_discrepancy(file_id: int, db_session: Session = Depends(get_db)):
    """Acknowledges a missing file — hides it from discrepancies."""
    record = db_session.get(models.FilesystemState, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File record not found")
    record.missing_acknowledged_at = datetime.now(timezone.utc)
    db_session.commit()
    return {"message": f"File '{record.file_path}' discrepancy dismissed"}


@router.post(
    "/discrepancies/{file_id}/undo-dismiss", operation_id="undo_dismiss_discrepancy"
)
def undo_dismiss_discrepancy(file_id: int, db_session: Session = Depends(get_db)):
    """Clears the acknowledged state so the file reappears in discrepancies (MEDIUM #22)."""
    record = db_session.get(models.FilesystemState, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File record not found")
    record.missing_acknowledged_at = None
    db_session.commit()
    return {
        "message": f"File '{record.file_path}' dismiss undone, will reappear in discrepancies"
    }


@router.delete("/discrepancies/{file_id}", operation_id="delete_discrepancy")
def delete_discrepancy(file_id: int, db_session: Session = Depends(get_db)):
    """Hard-deletes a file record and all associated versions/cart entries."""
    record = db_session.get(models.FilesystemState, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File record not found")
    db_session.query(models.RestoreCart).filter(
        models.RestoreCart.filesystem_state_id == file_id
    ).delete()
    db_session.query(models.FileVersion).filter(
        models.FileVersion.filesystem_state_id == file_id
    ).delete()
    file_path = record.file_path
    db_session.delete(record)
    db_session.commit()
    return {"message": f"File record '{file_path}' permanently deleted"}


# --- Discrepancy Tree & Browse Endpoints ---


@router.get(
    "/discrepancies/tree",
    response_model=List[TreeNodeSchema],
    operation_id="get_discrepancy_tree",
)
def get_discrepancy_tree(
    path: Optional[str] = Query(
        default="ROOT", description="Root path to get tree for"
    ),
    db_session: Session = Depends(get_db),
):
    """Returns tree of directories that contain discrepancy files, grouped by source root."""
    from app.api.archive import get_source_roots

    # Get source roots
    roots = get_source_roots(db_session)

    # Query all discrepancy files
    records = (
        db_session.query(models.FilesystemState)
        .filter(
            models.FilesystemState.is_ignored.is_(False),
            models.FilesystemState.missing_acknowledged_at.is_(None),
            (
                models.FilesystemState.is_deleted.is_(True)
                | models.FilesystemState.sha256_hash.is_(None)
            ),
        )
        .all()
    )

    # Build directory nodes keyed by directory path
    dir_nodes: Dict[str, TreeNodeSchema] = {}
    for record in records:
        directory = (
            record.file_path.rsplit("/", 1)[0] if "/" in record.file_path else ""
        )
        if directory not in dir_nodes:
            dir_nodes[directory] = TreeNodeSchema(
                name=directory.split("/")[-1] or directory or "ROOT",
                path=directory or "ROOT",
                has_children=True,
                children=[],
            )
        dir_nodes[directory].children.append(
            TreeNodeSchema(
                name=record.file_path.split("/")[-1],
                path=record.file_path,
                has_children=False,
            )
        )

    # If path is "ROOT", return top-level nodes grouped by source root
    if path == "ROOT":
        result = []
        seen = set()

        # First add source roots that have discrepancies
        for root in roots:
            root_dirs = [d for d in dir_nodes.keys() if d.startswith(root) or d == root]
            if root_dirs:
                children = [dir_nodes[d] for d in sorted(root_dirs)]
                result.append(
                    TreeNodeSchema(
                        name=root, path=root, has_children=True, children=children
                    )
                )
                seen.update(root_dirs)

        # Add directories that don't match any source root as themselves
        for d in sorted(dir_nodes.keys()):
            if d not in seen:
                result.append(dir_nodes[d])

        return result

    # Return immediate children of the given path
    if path is None:
        return []
    result = []
    for dir_path, node in sorted(dir_nodes.items()):
        if dir_path == path:
            return node.children
        elif dir_path.startswith(path + "/"):
            rel_path = dir_path[len(path) :].strip("/")
            if "/" not in rel_path:
                result.append(node)

    return result

    # Return immediate children of the given path
    result = []
    for dir_path, node in sorted(dir_nodes.items()):
        if dir_path == path:
            # This is the exact node - return its children
            return node.children
        elif dir_path.startswith(path + "/"):
            # This is a subdirectory - check if it's an immediate child
            rel_path = dir_path[len(path) :].strip("/")
            if "/" not in rel_path:
                # Immediate child
                result.append(node)

    return result

    # Return immediate children of the given path
    # Path could be a directory like "/data" - return its children
    result = []
    for dir_path, node in sorted(dir_nodes.items()):
        if dir_path == path:
            # This is the exact node - return its children
            return node.children
        elif dir_path.startswith(path + "/"):
            # This is a subdirectory - check if it's an immediate child
            rel_path = dir_path[len(path) :].strip("/")
            if "/" not in rel_path:
                # Immediate child
                result.append(node)

    return result


@router.get(
    "/discrepancies/browse", response_model=dict, operation_id="browse_discrepancies"
)
def browse_discrepancies(
    path: Optional[str] = Query(default="ROOT", description="Directory path to browse"),
    db_session: Session = Depends(get_db),
):
    """Returns discrepancy files and directories under a given directory path."""
    # Query all discrepancy files
    deleted_records = db_session.query(models.FilesystemState).filter(
        models.FilesystemState.is_deleted.is_(True),
        models.FilesystemState.is_ignored.is_(False),
        models.FilesystemState.missing_acknowledged_at.is_(None),
    )

    unhashed_missing = db_session.query(models.FilesystemState).filter(
        models.FilesystemState.sha256_hash.is_(None),
        models.FilesystemState.is_ignored.is_(False),
        models.FilesystemState.is_deleted.is_(False),
        models.FilesystemState.missing_acknowledged_at.is_(None),
    )

    # Batch-load valid version flags
    all_records = deleted_records.all() + unhashed_missing.all()
    record_ids = {r.id for r in all_records}
    ids_with_valid_versions = set()
    if record_ids:
        valid_version_rows = (
            db_session.query(models.FileVersion.filesystem_state_id)
            .join(models.StorageMedia)
            .filter(
                models.FileVersion.filesystem_state_id.in_(record_ids),
                models.StorageMedia.status.in_(["active", "full", "offline"]),
            )
            .distinct()
            .all()
        )
        ids_with_valid_versions = {row[0] for row in valid_version_rows}

    # Build a dict of all file paths
    all_paths = {r.file_path: r for r in all_records}

    # Find immediate children under the given path
    results = []
    seen_paths = set()

    for file_path, record in all_paths.items():
        if path == "ROOT":
            # For ROOT, show top-level directories/files
            if "/" in file_path:
                # It's in a subdirectory - get top-level dir
                parts = file_path.strip("/").split("/")
                top_dir = parts[0]
                child_path = "/" + top_dir
                child_name = top_dir
            else:
                # File at root
                child_path = file_path
                child_name = file_path
        else:
            # Check if this file is under the requested path
            if path is None or (
                file_path != path and not file_path.startswith(path + "/")
            ):
                continue

            # Get immediate child relative to path
            path_str = path or ""
            rel_path = file_path[len(path_str) :].strip("/")
            if "/" in rel_path:
                # It's a subdirectory - get immediate child
                child_name = rel_path.split("/")[0]
                child_path = (
                    path_str + "/" + child_name if path_str != "/" else "/" + child_name
                )
            else:
                # It's a file
                child_path = file_path
                child_name = rel_path

        # Skip duplicates
        if child_path in seen_paths:
            continue
        seen_paths.add(child_path)

        # Check if it's a directory or file
        is_dir = any(
            p != child_path and p.startswith(child_path + "/") for p in all_paths
        )

        if is_dir:
            # Count discrepancy files in this directory
            file_count = sum(1 for p in all_paths if p.startswith(child_path + "/"))
            results.append(
                {
                    "name": child_name,
                    "path": child_path,
                    "type": "directory",
                    "has_children": file_count > 0,
                    "discrepancy_count": file_count,
                }
            )
        else:
            # It's a file
            has_valid_versions = record.id in ids_with_valid_versions
            results.append(
                DiscrepancySchema(
                    id=record.id,
                    path=record.file_path,
                    size=record.size,
                    mtime=datetime.fromtimestamp(record.mtime, tz=timezone.utc),
                    last_seen_timestamp=record.last_seen_timestamp,
                    sha256_hash=record.sha256_hash,
                    is_deleted=record.is_deleted,
                    has_versions=has_valid_versions,
                )
            )

    return {"files": results}
