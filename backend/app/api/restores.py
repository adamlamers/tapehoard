from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text
from app.db.database import get_db, SessionLocal
from app.db import models
from app.services.archiver import archiver_manager
from app.services.scanner import JobManager
from loguru import logger

router = APIRouter(prefix="/restores", tags=["Restores"])


# --- Request/Response Schemas ---


class CartItemSchema(BaseModel):
    id: int
    file_path: str
    size: int
    type: str

    class Config:
        from_attributes = True


class RestoreTriggerRequest(BaseModel):
    destination_path: str


class CartFileItemSchema(BaseModel):
    name: str
    path: str
    type: str
    size: Optional[int] = None
    mtime: Optional[float] = None
    vulnerable: bool = False
    selected: bool = False
    indeterminate: bool = False


class CartTreeNodeSchema(BaseModel):
    name: str
    path: str
    has_children: bool = False


class ManifestMediaSchema(BaseModel):
    identifier: str
    media_type: str
    file_count: int
    total_size: int


class RestoreManifestSchema(BaseModel):
    total_files: int
    total_size: int
    media_required: List[ManifestMediaSchema]


class DirectoryCartRequest(BaseModel):
    path: str


# --- Endpoints ---


@router.get("/cart", response_model=List[CartItemSchema])
def list_recovery_queue(db_session: Session = Depends(get_db)):
    """Returns all items currently queued for data recovery."""
    queue_items = (
        db_session.query(models.RestoreCart)
        .options(joinedload(models.RestoreCart.file_state))
        .all()
    )
    return [
        CartItemSchema(
            id=item.id,
            file_path=item.file_state.file_path,
            size=item.file_state.size,
            type="file",
        )
        for item in queue_items
    ]


@router.post("/cart/clear")
def clear_recovery_queue(db_session: Session = Depends(get_db)):
    """Removes all items from the data recovery queue."""
    db_session.query(models.RestoreCart).delete()
    db_session.commit()
    return {"message": "Recovery queue cleared."}


@router.post("/cart/{file_id}")
def add_file_to_recovery_queue(file_id: int, db_session: Session = Depends(get_db)):
    """Adds a specific file to the recovery queue if it has valid backups."""
    existing_item = (
        db_session.query(models.RestoreCart)
        .filter(models.RestoreCart.filesystem_state_id == file_id)
        .first()
    )
    if existing_item:
        return {"message": "Item already in queue."}

    file_record = db_session.get(models.FilesystemState, file_id)
    if not file_record or not file_record.versions:
        raise HTTPException(
            status_code=400,
            detail="File has no backed up versions and cannot be recovered.",
        )

    new_queue_item = models.RestoreCart(filesystem_state_id=file_id)
    db_session.add(new_queue_item)
    db_session.commit()
    return {"message": "Added to recovery queue."}


@router.delete("/cart/{item_id}")
def remove_from_recovery_queue(item_id: int, db_session: Session = Depends(get_db)):
    """Removes a specific item from the data recovery queue."""
    queue_item = db_session.get(models.RestoreCart, item_id)
    if queue_item:
        db_session.delete(queue_item)
        db_session.commit()
    return {"message": "Removed from recovery queue."}


@router.post("/cart/directory")
def add_directory_to_recovery_queue(
    request_data: DirectoryCartRequest, db_session: Session = Depends(get_db)
):
    """Recursively adds all restorable files within a directory to the recovery queue."""
    target_directory = request_data.path
    if not target_directory.endswith("/"):
        target_directory += "/"

    # Efficient bulk insert: Find all indexed files under this path that have AT LEAST ONE version
    # and ARE NOT already in the cart.
    discovery_sql = text("""
        INSERT INTO restore_cart (filesystem_state_id)
        SELECT DISTINCT fs.id
        FROM filesystem_state fs
        JOIN file_versions fv ON fv.filesystem_state_id = fs.id
        LEFT JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
        WHERE fs.file_path LIKE :prefix
        AND rc.id IS NULL
    """)

    db_session.execute(discovery_sql, {"prefix": f"{target_directory}%"})
    db_session.commit()

    total_in_queue = db_session.query(models.RestoreCart).count()
    logger.info(f"Directory recovery queued. Total items: {total_in_queue}")

    return {"message": f"Added restorable items from {target_directory} to queue."}


@router.get("/manifest", response_model=RestoreManifestSchema)
def calculate_recovery_manifest(db_session: Session = Depends(get_db)):
    """Generates an optimized physical media manifest for the current recovery queue."""
    manifest_sql = text("""
        SELECT
            sm.identifier,
            sm.media_type,
            COUNT(DISTINCT fs.id) as file_count,
            SUM(fv.offset_end - fv.offset_start) as total_size
        FROM filesystem_state fs
        JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
        JOIN file_versions fv ON fv.filesystem_state_id = fs.id
        JOIN storage_media sm ON sm.id = fv.media_id
        WHERE fv.id = (
            SELECT id FROM file_versions
            WHERE filesystem_state_id = fs.id
            ORDER BY created_at DESC LIMIT 1
        )
        GROUP BY sm.identifier, sm.media_type
    """)

    manifest_rows = db_session.execute(manifest_sql).fetchall()
    media_requirements = [
        ManifestMediaSchema(
            identifier=row[0], media_type=row[1], file_count=row[2], total_size=row[3]
        )
        for row in manifest_rows
    ]

    total_count = sum(media.file_count for media in media_requirements)
    total_bytes = sum(media.total_size for media in media_requirements)

    return RestoreManifestSchema(
        total_files=total_count,
        total_size=total_bytes,
        media_required=media_requirements,
    )


@router.post("/trigger")
def trigger_recovery_job(
    request_data: RestoreTriggerRequest,
    background_tasks: BackgroundTasks,
    db_session: Session = Depends(get_db),
):
    """Initiates the background physical recovery process to the specified destination."""
    destination_root = request_data.destination_path

    # Pre-validation of queue
    queue_count = db_session.query(models.RestoreCart).count()
    if queue_count == 0:
        raise HTTPException(status_code=400, detail="Recovery queue is empty.")

    job_record = JobManager.create_job(db_session, "RESTORE")

    def run_recovery_task():
        with SessionLocal() as db_inner:
            archiver_manager.run_restore(db_inner, destination_root, job_record.id)

    background_tasks.add_task(run_recovery_task)
    return {"message": "Recovery job initiated.", "job_id": job_record.id}


@router.get("/cart/browse", response_model=List[CartFileItemSchema])
def browse_recovery_queue_virtual_fs(
    path: Optional[str] = None, db_session: Session = Depends(get_db)
):
    """Provides a virtual browsable view of the recovery queue."""
    from app.api.system import get_source_roots

    source_roots = get_source_roots(db_session)

    if path is None or path == "ROOT":
        results = []
        for root_path in source_roots:
            stats_sql = text("""
                SELECT COUNT(*) FROM filesystem_state fs
                JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
                WHERE fs.file_path LIKE :prefix
            """)
            count = (
                db_session.execute(stats_sql, {"prefix": f"{root_path}%"}).scalar() or 0
            )
            if count > 0:
                results.append(
                    CartFileItemSchema(
                        name=root_path, path=root_path, type="directory", selected=True
                    )
                )
        return results

    path_prefix = path if path.endswith("/") else path + "/"
    results = []

    # Virtual directory aggregation
    dir_agg_sql = text("""
        SELECT DISTINCT SUBSTR(fs.file_path, LENGTH(:prefix) + 1, INSTR(SUBSTR(fs.file_path, LENGTH(:prefix) + 1), '/') - 1) as dirname
        FROM filesystem_state fs
        JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
        WHERE fs.file_path LIKE :search_prefix
        AND SUBSTR(fs.file_path, LENGTH(:prefix) + 1) LIKE '%/%'
    """)
    virtual_dirs = db_session.execute(
        dir_agg_sql, {"prefix": path_prefix, "search_prefix": f"{path_prefix}%"}
    ).fetchall()
    for dir_row in virtual_dirs:
        if dir_row[0]:
            results.append(
                CartFileItemSchema(
                    name=dir_row[0],
                    path=path_prefix + dir_row[0],
                    type="directory",
                    selected=True,
                )
            )

    # Actual files in the cart
    file_agg_sql = text("""
        SELECT fs.file_path, fs.size, fs.mtime
        FROM filesystem_state fs
        JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
        WHERE fs.file_path LIKE :search_prefix
        AND SUBSTR(fs.file_path, LENGTH(:prefix) + 1) NOT LIKE '%/%'
    """)
    cart_files = db_session.execute(
        file_agg_sql, {"prefix": path_prefix, "search_prefix": f"{path_prefix}%"}
    ).fetchall()
    for file_row in cart_files:
        results.append(
            CartFileItemSchema(
                name=file_row[0].split("/")[-1],
                path=file_row[0],
                type="file",
                size=file_row[1],
                mtime=file_row[2],
                selected=True,
            )
        )

    results.sort(key=lambda x: (x.type != "directory", x.name.lower()))
    return results


@router.get("/cart/tree", response_model=List[CartTreeNodeSchema])
def get_recovery_queue_tree(
    path: Optional[str] = None, db_session: Session = Depends(get_db)
):
    """Returns a recursive tree view of the recovery queue's virtual filesystem."""
    from app.api.system import get_source_roots

    source_roots = get_source_roots(db_session)

    if path is None or path == "ROOT":
        results = []
        for root_path in source_roots:
            stats_sql = text("""
                SELECT 1 FROM filesystem_state fs
                JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
                WHERE fs.file_path LIKE :prefix LIMIT 1
            """)
            if db_session.execute(stats_sql, {"prefix": f"{root_path}%"}).scalar():
                results.append(
                    CartTreeNodeSchema(
                        name=root_path, path=root_path, has_children=True
                    )
                )
        return results

    path_prefix = path if path.endswith("/") else path + "/"
    subdir_sql = text("""
        SELECT DISTINCT SUBSTR(fs.file_path, LENGTH(:prefix) + 1, INSTR(SUBSTR(fs.file_path, LENGTH(:prefix) + 1), '/') - 1) as dirname
        FROM filesystem_state fs
        JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
        WHERE fs.file_path LIKE :search_prefix
        AND SUBSTR(fs.file_path, LENGTH(:prefix) + 1) LIKE '%/%'
    """)
    subdirs = db_session.execute(
        subdir_sql, {"prefix": path_prefix, "search_prefix": f"{path_prefix}%"}
    ).fetchall()

    results = [
        CartTreeNodeSchema(name=row[0], path=path_prefix + row[0], has_children=True)
        for row in subdirs
        if row[0]
    ]
    results.sort(key=lambda x: x.name.lower())
    return results
