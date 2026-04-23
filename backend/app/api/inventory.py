from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.database import get_db
from app.db import models
from datetime import datetime, timezone
import json
import os

router = APIRouter(prefix="/inventory", tags=["Inventory"])


# --- Helpers ---
def get_source_roots(db: Session) -> List[str]:
    setting = (
        db.query(models.SystemSetting)
        .filter(models.SystemSetting.key == "source_roots")
        .first()
    )
    if setting:
        try:
            return json.loads(setting.value)
        except Exception:
            return [setting.value]
    local_source = os.path.abspath(os.path.join(os.getcwd(), "..", "source_data"))
    if os.path.exists(local_source):
        return [local_source]
    return ["/source_data"]


# --- Schemas ---


class FileVersionSchema(BaseModel):
    media_identifier: str
    media_type: str
    file_number: str
    timestamp: datetime


class ItemMetadataSchema(BaseModel):
    id: Optional[int] = None  # Added for file operations
    file_path: str
    type: str
    size: int
    mtime: float
    last_seen_timestamp: datetime
    sha256_hash: Optional[str] = None
    versions: List[FileVersionSchema] = []
    child_count: Optional[int] = None


class FileItemSchema(BaseModel):
    name: str
    path: str
    type: str
    size: Optional[int] = None
    mtime: Optional[float] = None
    media: List[str] = []


class TreeNodeSchema(BaseModel):
    name: str
    path: str
    has_children: bool = False


class MediaCreateSchema(BaseModel):
    media_type: str  # tape, hdd, cloud
    identifier: str
    generation_tier: Optional[str] = None
    capacity: int  # in bytes
    location: Optional[str] = None
    config: Dict[str, Any] = {}


class MediaUpdateSchema(BaseModel):
    status: Optional[str] = None
    location: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class MediaSchema(BaseModel):
    id: int
    media_type: str
    identifier: str
    generation_tier: Optional[str]
    capacity: int
    bytes_used: int
    location: Optional[str]
    status: str
    config: Dict[str, Any]

    @classmethod
    def from_orm_custom(cls, obj: models.StorageMedia):
        config_data = {}
        if obj.extra_config:
            try:
                config_data = json.loads(obj.extra_config)
            except Exception:
                pass
        return cls(
            id=obj.id,
            media_type=obj.media_type,
            identifier=obj.identifier,
            generation_tier=obj.generation_tier,
            capacity=obj.capacity,
            bytes_used=obj.bytes_used,
            location=obj.location,
            status=obj.status,
            config=config_data,
        )


# --- Media Endpoints ---


@router.get("/media", response_model=List[MediaSchema])
def list_media(db: Session = Depends(get_db)):
    all_media = db.query(models.StorageMedia).all()
    return [MediaSchema.from_orm_custom(m) for m in all_media]


@router.post("/media", response_model=MediaSchema)
def register_media(req: MediaCreateSchema, db: Session = Depends(get_db)):
    existing = (
        db.query(models.StorageMedia)
        .filter(models.StorageMedia.identifier == req.identifier)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400, detail="Media with this identifier already exists"
        )
    new_media = models.StorageMedia(
        media_type=req.media_type,
        identifier=req.identifier,
        generation_tier=req.generation_tier,
        capacity=req.capacity,
        location=req.location,
        status="active",
        extra_config=json.dumps(req.config),
    )
    db.add(new_media)
    db.commit()
    db.refresh(new_media)
    return MediaSchema.from_orm_custom(new_media)


@router.patch("/media/{media_id}", response_model=MediaSchema)
def update_media(media_id: int, req: MediaUpdateSchema, db: Session = Depends(get_db)):
    media = db.query(models.StorageMedia).get(media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    if req.status:
        media.status = req.status
    if req.location:
        media.location = req.location
    if req.config is not None:
        current_config = {}
        if media.extra_config:
            try:
                current_config = json.loads(media.extra_config)
            except Exception:
                pass
        current_config.update(req.config)
        media.extra_config = json.dumps(current_config)
    db.commit()
    db.refresh(media)
    return MediaSchema.from_orm_custom(media)


@router.delete("/media/{media_id}")
def delete_media(media_id: int, db: Session = Depends(get_db)):
    media = db.query(models.StorageMedia).get(media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")
    if media.versions:
        raise HTTPException(status_code=400, detail="Cannot delete media with files")
    db.delete(media)
    db.commit()
    return {"message": "Media deleted"}


# --- Browsing Endpoints (Optimized) ---


@router.get("/browse", response_model=List[FileItemSchema])
def browse_index(
    path: Optional[str] = None,
    include_ignored: bool = False,
    db: Session = Depends(get_db),
):
    if path is None or path == "ROOT":
        roots = get_source_roots(db)
        results = []
        for root in roots:
            sql = text(
                "SELECT COUNT(*), SUM(size), MAX(mtime) FROM filesystem_state WHERE file_path LIKE :prefix"
                + (" AND is_ignored = 0" if not include_ignored else "")
            )
            row = db.execute(sql, {"prefix": f"{root}%"}).fetchone()
            if row and row[0] > 0:
                results.append(
                    FileItemSchema(
                        name=root,
                        path=root,
                        type="directory",
                        size=row[1] or 0,
                        mtime=row[2] or 0,
                    )
                )
        return results

    prefix = path if path.endswith("/") else path + "/"
    ignore_filter = " AND is_ignored = 0" if not include_ignored else ""
    results = []

    # Subdirectories
    subdir_sql = text(
        f"""
        SELECT DISTINCT SUBSTR(file_path, LENGTH(:prefix) + 1, INSTR(SUBSTR(file_path, LENGTH(:prefix) + 1), '/') - 1) as dirname
        FROM filesystem_state WHERE file_path LIKE :search_prefix AND SUBSTR(file_path, LENGTH(:prefix) + 1) LIKE '%/%' {ignore_filter}
    """
    )
    subdirs = db.execute(
        subdir_sql, {"prefix": prefix, "search_prefix": f"{prefix}%"}
    ).fetchall()
    for sd in subdirs:
        if sd[0]:
            results.append(
                FileItemSchema(
                    name=sd[0], path=prefix + sd[0], type="directory", size=0, mtime=0
                )
            )

    # Files
    file_sql = text(
        f"""
        SELECT name, file_path, size, mtime, id FROM (
            SELECT SUBSTR(file_path, LENGTH(:prefix) + 1) as name, file_path, size, mtime, id
            FROM filesystem_state WHERE file_path LIKE :search_prefix {ignore_filter}
        ) WHERE name NOT LIKE '%/%'
    """
    )
    files = db.execute(
        file_sql, {"prefix": prefix, "search_prefix": f"{prefix}%"}
    ).fetchall()
    for f in files:
        media_sql = text(
            "SELECT m.identifier FROM storage_media m JOIN file_versions v ON v.media_id = m.id WHERE v.filesystem_state_id = :fid"
        )
        media_list = [m[0] for m in db.execute(media_sql, {"fid": f[4]}).fetchall()]
        results.append(
            FileItemSchema(
                name=f[0],
                path=f[1],
                type="file",
                size=f[2],
                mtime=f[3],
                media=media_list,
            )
        )

    results.sort(key=lambda x: (x.type != "directory", x.name.lower()))
    return results


@router.get("/tree", response_model=List[TreeNodeSchema])
def get_index_tree(
    path: Optional[str] = None,
    include_ignored: bool = False,
    db: Session = Depends(get_db),
):
    if path is None or path == "ROOT":
        roots = get_source_roots(db)
        return [TreeNodeSchema(name=r, path=r, has_children=True) for r in roots]
    prefix = path if path.endswith("/") else path + "/"
    ignore_filter = " AND is_ignored = 0" if not include_ignored else ""
    subdir_sql = text(
        f"SELECT DISTINCT SUBSTR(file_path, LENGTH(:prefix) + 1, INSTR(SUBSTR(file_path, LENGTH(:prefix) + 1), '/') - 1) as dirname FROM filesystem_state WHERE file_path LIKE :search_prefix AND SUBSTR(file_path, LENGTH(:prefix) + 1) LIKE '%/%' {ignore_filter}"
    )
    subdirs = db.execute(
        subdir_sql, {"prefix": prefix, "search_prefix": f"{prefix}%"}
    ).fetchall()
    results = [
        TreeNodeSchema(name=sd[0], path=prefix + sd[0], has_children=True)
        for sd in subdirs
        if sd[0]
    ]
    results.sort(key=lambda x: x.name.lower())
    return results


@router.get("/metadata", response_model=ItemMetadataSchema)
def get_item_metadata(path: str, db: Session = Depends(get_db)):
    file_state = (
        db.query(models.FilesystemState)
        .filter(models.FilesystemState.file_path == path)
        .first()
    )
    if file_state:
        versions = [
            FileVersionSchema(
                media_identifier=v.media.identifier,
                media_type=v.media.media_type,
                file_number=v.file_number,
                timestamp=file_state.last_seen_timestamp,
            )
            for v in file_state.versions
        ]
        return ItemMetadataSchema(
            id=file_state.id,  # Now included
            file_path=file_state.file_path,
            type="file",
            size=file_state.size,
            mtime=file_state.mtime,
            last_seen_timestamp=file_state.last_seen_timestamp,
            sha256_hash=file_state.sha256_hash,
            versions=versions,
        )
    prefix = path if path.endswith("/") else path + "/"
    sql = text(
        "SELECT COUNT(*), SUM(size), MAX(mtime), MAX(last_seen_timestamp) FROM filesystem_state WHERE file_path LIKE :prefix AND is_ignored = 0"
    )
    row = db.execute(sql, {"prefix": f"{prefix}%"}).fetchone()
    if row and row[0] > 0:
        return ItemMetadataSchema(
            file_path=path,
            type="directory",
            size=row[1] or 0,
            mtime=row[2] or 0,
            last_seen_timestamp=row[3] or datetime.now(timezone.utc),
            child_count=row[0],
        )
    raise HTTPException(status_code=404, detail="Item not found")


@router.get("/")
def list_inventory():
    return []
