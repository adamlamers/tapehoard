from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text
from app.db.database import get_db, SessionLocal
from app.db import models
from datetime import datetime, timezone
from app.services.archiver import archiver_manager
from app.services.scanner import JobManager

router = APIRouter(prefix="/restores", tags=["Restores"])

# --- Schemas ---


class CartItemSchema(BaseModel):
    id: int
    file_path: str
    size: int
    media_identifiers: List[str]

    class Config:
        from_attributes = True


class ManifestMediaRequirement(BaseModel):
    identifier: str
    media_type: str
    file_count: int
    total_size: int


class RestoreManifestSchema(BaseModel):
    total_files: int
    total_size: int
    media_required: List[ManifestMediaRequirement]


class RestoreRequest(BaseModel):
    destination: str


class DirectoryCartRequest(BaseModel):
    path: str


class CartFileItemSchema(BaseModel):
    name: str
    path: str
    type: str
    size: Optional[int] = None
    media: List[str] = []


class CartTreeNodeSchema(BaseModel):
    name: str
    path: str
    has_children: bool = False


# --- Endpoints ---


@router.post("/trigger")
def trigger_restore(
    req: RestoreRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    cart_items = db.query(models.RestoreCart).all()
    if not cart_items:
        raise HTTPException(status_code=400, detail="Recovery queue is empty")

    job = JobManager.create_job(db, "RESTORE")

    def run_restore_task():
        db_inner = SessionLocal()
        try:
            archiver_manager.run_restore(
                db_inner, destination=req.destination, job_id=job.id
            )
        finally:
            db_inner.close()

    background_tasks.add_task(run_restore_task)
    return {"message": "Restore job initiated", "job_id": job.id}


@router.get("/cart/browse", response_model=List[CartFileItemSchema])
def browse_cart(path: Optional[str] = None, db: Session = Depends(get_db)):
    from app.api.inventory import get_source_roots

    roots = get_source_roots(db)

    if path is None or path == "ROOT":
        results = []
        for root in roots:
            # Check if any file in the cart is under this root
            prefix = root if root.endswith("/") else root + "/"
            sql = text("""
                SELECT EXISTS (
                    SELECT 1 FROM filesystem_state fs
                    JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
                    WHERE fs.file_path LIKE :prefix
                )
            """)
            if db.execute(sql, {"prefix": f"{prefix}%"}).scalar():
                results.append(
                    CartFileItemSchema(name=root, path=root, type="directory")
                )
        return results

    prefix = path if path.endswith("/") else path + "/"
    results = []

    # Subdirectories in cart
    subdir_sql = text("""
        SELECT DISTINCT SUBSTR(fs.file_path, LENGTH(:prefix) + 1, INSTR(SUBSTR(fs.file_path, LENGTH(:prefix) + 1), '/') - 1) as dirname
        FROM filesystem_state fs
        JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
        WHERE fs.file_path LIKE :search_prefix
        AND SUBSTR(fs.file_path, LENGTH(:prefix) + 1) LIKE '%/%'
    """)
    subdirs = db.execute(
        subdir_sql, {"prefix": prefix, "search_prefix": f"{prefix}%"}
    ).fetchall()
    for sd in subdirs:
        if sd[0]:
            results.append(
                CartFileItemSchema(name=sd[0], path=prefix + sd[0], type="directory")
            )

    # Files in cart
    file_sql = text("""
        SELECT fs.file_path, fs.size, fs.id, GROUP_CONCAT(sm.identifier) as media_list
        FROM filesystem_state fs
        JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
        JOIN file_versions fv ON fv.filesystem_state_id = fs.id
        JOIN storage_media sm ON sm.id = fv.media_id
        WHERE fs.file_path LIKE :search_prefix
        AND SUBSTR(fs.file_path, LENGTH(:prefix) + 1) NOT LIKE '%/%'
        GROUP BY fs.id
    """)
    files = db.execute(
        file_sql, {"prefix": prefix, "search_prefix": f"{prefix}%"}
    ).fetchall()
    for f in files:
        results.append(
            CartFileItemSchema(
                name=f[0].split("/")[-1],
                path=f[0],
                type="file",
                size=f[1],
                media=f[3].split(",") if f[3] else [],
            )
        )

    results.sort(key=lambda x: (x.type != "directory", x.name.lower()))
    return results


@router.get("/cart/tree", response_model=List[CartTreeNodeSchema])
def get_cart_tree(path: Optional[str] = None, db: Session = Depends(get_db)):
    from app.api.inventory import get_source_roots

    roots = get_source_roots(db)

    if path is None or path == "ROOT":
        results = []
        for root in roots:
            prefix = root if root.endswith("/") else root + "/"
            sql = text("""
                SELECT EXISTS (
                    SELECT 1 FROM filesystem_state fs
                    JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
                    WHERE fs.file_path LIKE :prefix
                )
            """)
            if db.execute(sql, {"prefix": f"{prefix}%"}).scalar():
                results.append(
                    CartTreeNodeSchema(name=root, path=root, has_children=True)
                )
        return results

    prefix = path if path.endswith("/") else path + "/"
    subdir_sql = text("""
        SELECT DISTINCT SUBSTR(fs.file_path, LENGTH(:prefix) + 1, INSTR(SUBSTR(fs.file_path, LENGTH(:prefix) + 1), '/') - 1) as dirname
        FROM filesystem_state fs
        JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
        WHERE fs.file_path LIKE :search_prefix
        AND SUBSTR(fs.file_path, LENGTH(:prefix) + 1) LIKE '%/%'
    """)
    subdirs = db.execute(
        subdir_sql, {"prefix": prefix, "search_prefix": f"{prefix}%"}
    ).fetchall()
    results = [
        CartTreeNodeSchema(name=sd[0], path=prefix + sd[0], has_children=True)
        for sd in subdirs
        if sd[0]
    ]
    results.sort(key=lambda x: x.name.lower())
    return results


@router.get("/cart", response_model=List[CartItemSchema])
def list_cart(db: Session = Depends(get_db)):
    # OPTIMIZED: Use joinedload to fetch all versions in a single query
    items = (
        db.query(models.RestoreCart)
        .options(
            joinedload(models.RestoreCart.file_state)
            .joinedload(models.FilesystemState.versions)
            .joinedload(models.FileVersion.media)
        )
        .all()
    )

    results = []
    for item in items:
        media_ids = [v.media.identifier for v in item.file_state.versions]
        results.append(
            CartItemSchema(
                id=item.id,
                file_path=item.file_state.file_path,
                size=item.file_state.size,
                media_identifiers=media_ids,
            )
        )
    return results


# NOTE: Static routes MUST come before parameterized ones like /cart/{file_id}


@router.post("/cart/clear")
def clear_cart(db: Session = Depends(get_db)):
    db.query(models.RestoreCart).delete(synchronize_session=False)
    db.commit()
    return {"message": "Recovery queue cleared"}


@router.post("/cart/directory")
def add_directory_to_cart(req: DirectoryCartRequest, db: Session = Depends(get_db)):
    from loguru import logger

    path = req.path
    if path == "ROOT":
        prefix_query = "%"
        exact_path = "ROOT"
    else:
        prefix = path if path.endswith("/") else path + "/"
        prefix_query = f"{prefix}%"
        exact_path = path

    logger.info(f"Adding directory to queue: {path} (prefix: {prefix_query})")

    # Optimized SQL for lightning-fast bulk insert
    # 1. Matches path prefix (using the new index)
    # 2. Joins file_versions to ensure it's restorable
    # 3. Left Joins restore_cart to skip already-queued items
    insert_sql = text("""
        INSERT INTO restore_cart (filesystem_state_id, created_at)
        SELECT DISTINCT fs.id, :now
        FROM filesystem_state fs
        JOIN file_versions fv ON fv.filesystem_state_id = fs.id
        LEFT JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
        WHERE (fs.file_path = :path OR fs.file_path LIKE :prefix)
        AND rc.id IS NULL
    """)

    db.execute(
        insert_sql,
        {
            "path": exact_path,
            "prefix": prefix_query,
            "now": datetime.now(timezone.utc).isoformat(),
        },
    )

    db.commit()

    total_in_cart = db.query(models.RestoreCart).count()
    logger.info(f"Directory add complete. Total in cart: {total_in_cart}")

    return {"message": f"Added restorable items from {path} to recovery queue"}


@router.post("/cart/{file_id}")
def add_to_cart(file_id: int, db: Session = Depends(get_db)):
    existing = (
        db.query(models.RestoreCart)
        .filter(models.RestoreCart.filesystem_state_id == file_id)
        .first()
    )
    if existing:
        return {"message": "Already in recovery queue"}

    file_state = db.get(models.FilesystemState, file_id)
    if not file_state or not file_state.versions:
        raise HTTPException(status_code=400, detail="File has no backed up versions")

    new_item = models.RestoreCart(filesystem_state_id=file_id)
    db.add(new_item)
    db.commit()
    return {"message": "Added to recovery queue"}


@router.delete("/cart/{item_id}")
def remove_from_cart(item_id: int, db: Session = Depends(get_db)):
    item = db.get(models.RestoreCart, item_id)
    if item:
        db.delete(item)
        db.commit()
    return {"message": "Removed from recovery queue"}


@router.get("/manifest", response_model=RestoreManifestSchema)
def get_manifest(db: Session = Depends(get_db)):
    # OPTIMIZED: Use a single raw SQL query to calculate the entire manifest
    # This completely avoids loading thousands of ORM objects into memory
    sql = text("""
        SELECT
            sm.identifier,
            sm.media_type,
            COUNT(DISTINCT fs.id) as file_count,
            SUM(fv.offset_end - fv.offset_start) as total_size
        FROM filesystem_state fs
        JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
        JOIN file_versions fv ON fv.filesystem_state_id = fs.id
        JOIN storage_media sm ON sm.id = fv.media_id
        GROUP BY sm.id
    """)

    rows = db.execute(sql).fetchall()

    requirements = []
    total_size = 0

    # We also need the total unique files in the cart (a file might be on multiple media)
    total_unique_files = db.query(models.RestoreCart).count()

    for row in rows:
        requirements.append(
            ManifestMediaRequirement(
                identifier=row[0],
                media_type=row[1],
                file_count=row[2],
                total_size=row[3],
            )
        )
        total_size += row[3]

    requirements.sort(key=lambda x: x.identifier)

    return RestoreManifestSchema(
        total_files=total_unique_files,
        total_size=total_size,
        media_required=requirements,
    )
