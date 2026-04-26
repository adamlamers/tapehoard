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
    vulnerable: bool = False
    selected: bool = False
    indeterminate: bool = False


class FileItemSchema(BaseModel):
    name: str
    path: str
    type: str
    size: Optional[int] = None
    mtime: Optional[float] = None
    media: List[str] = []
    vulnerable: bool = False
    selected: bool = False
    indeterminate: bool = False


class TreeNodeSchema(BaseModel):
    name: str
    path: str
    has_children: bool = False


class MediaCreateSchema(BaseModel):
    media_type: str
    identifier: str
    generation_tier: Optional[str] = None
    capacity: int
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
    is_online: bool = False
    is_identified: bool = False
    priority_index: int = 0

    class Config:
        from_attributes = True


class ReorderMediaRequest(BaseModel):
    media_ids: List[int]


# --- Media Management ---


@router.get("/media", response_model=List[MediaSchema])
def list_media(db: Session = Depends(get_db)):
    from app.services.archiver import archiver_manager

    media = (
        db.query(models.StorageMedia)
        .order_by(models.StorageMedia.priority_index.asc())
        .all()
    )
    results = []
    for m in media:
        config = {}
        if m.extra_config:
            try:
                config = json.loads(m.extra_config)
            except Exception:
                pass

        # Perform a pulse check on the hardware
        is_online = False
        is_identified = False
        provider = archiver_manager._get_provider(m)
        if provider:
            is_online = provider.check_online()
            if is_online:
                current_id = provider.identify_media()
                is_identified = current_id == m.identifier

        results.append(
            MediaSchema(
                id=m.id,
                media_type=m.media_type,
                identifier=m.identifier,
                generation_tier=m.generation_tier,
                capacity=m.capacity,
                bytes_used=m.bytes_used,
                location=m.location,
                status=m.status,
                config=config,
                is_online=is_online,
                is_identified=is_identified,
                priority_index=m.priority_index,
            )
        )
    return results


@router.post("/media/reorder")
def reorder_media(req: ReorderMediaRequest, db: Session = Depends(get_db)):
    for index, media_id in enumerate(req.media_ids):
        media = db.get(models.StorageMedia, media_id)
        if media:
            media.priority_index = index
    db.commit()
    return {"message": "Media priority updated"}


@router.post("/media", response_model=MediaSchema)
def register_media(req: MediaCreateSchema, db: Session = Depends(get_db)):
    existing = (
        db.query(models.StorageMedia)
        .filter(models.StorageMedia.identifier == req.identifier)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail="Media already exists")

    new_media = models.StorageMedia(
        media_type=req.media_type,
        identifier=req.identifier,
        generation_tier=req.generation_tier,
        capacity=req.capacity,
        location=req.location,
        extra_config=json.dumps(req.config),
    )
    db.add(new_media)
    db.commit()
    db.refresh(new_media)

    config = {}
    if new_media.extra_config:
        config = json.loads(new_media.extra_config)

    return MediaSchema(
        id=new_media.id,
        media_type=new_media.media_type,
        identifier=new_media.identifier,
        generation_tier=new_media.generation_tier,
        capacity=new_media.capacity,
        bytes_used=new_media.bytes_used,
        location=new_media.location,
        status=new_media.status,
        config=config,
    )


@router.patch("/media/{media_id}", response_model=MediaSchema)
def update_media(media_id: int, req: MediaUpdateSchema, db: Session = Depends(get_db)):
    media = db.get(models.StorageMedia, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    if req.status:
        media.status = req.status
    if req.location:
        media.location = req.location
    if req.config:
        media.extra_config = json.dumps(req.config)

    db.commit()
    db.refresh(media)
    config = {}
    if media.extra_config:
        config = json.loads(media.extra_config)

    return MediaSchema(
        id=media.id,
        media_type=media.media_type,
        identifier=media.identifier,
        generation_tier=media.generation_tier,
        capacity=media.capacity,
        bytes_used=media.bytes_used,
        location=media.location,
        status=media.status,
        config=config,
    )


@router.delete("/media/{media_id}")
def delete_media(media_id: int, db: Session = Depends(get_db)):
    media = db.get(models.StorageMedia, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    # Cascade delete versions associated with this media
    if media.versions:
        for version in media.versions:
            db.delete(version)

    db.delete(media)
    db.commit()
    return {"message": "Media and associated version history deleted"}


@router.post("/media/{media_id}/initialize")
def initialize_media(media_id: int, force: bool = False, db: Session = Depends(get_db)):
    from app.services.archiver import archiver_manager

    media = db.get(models.StorageMedia, media_id)
    if not media:
        raise HTTPException(status_code=404, detail="Media not found")

    provider = archiver_manager._get_provider(media)
    if not provider:
        raise HTTPException(status_code=400, detail="Unsupported media type")

    # Check for existing data if not forcing
    if not force:
        if provider.check_existing_data():
            raise HTTPException(
                status_code=409,
                detail=f"Media {media.identifier} already contains TapeHoard backups. Initializing will delete them. Continue?",
            )

    if provider.initialize_media(media.identifier):
        return {"message": "Media initialized successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to initialize media")


# --- Browsing Endpoints (Highly Optimized) ---


@router.get("/insights")
def get_filesystem_insights(db: Session = Depends(get_db)):
    """Computes high-signal filesystem metrics for modular reporting"""

    # 1. Deduplication & Scale
    # We compare total indexed size vs unique hash size
    dedupe_sql = text("""
        SELECT
            SUM(size) as total_size,
            COUNT(*) as total_files,
            (SELECT SUM(size) FROM (SELECT size FROM filesystem_state WHERE is_indexed = 1 GROUP BY sha256_hash)) as unique_size
        FROM filesystem_state
    """)
    dedupe = db.execute(dedupe_sql).fetchone()

    # 2. Vulnerability by Root
    roots = get_source_roots(db)
    root_stats = []
    for root in roots:
        prefix = root if root.endswith("/") else root + "/"
        stats_sql = text("""
            SELECT
                SUM(CASE WHEN fv.id IS NOT NULL THEN fs.size ELSE 0 END) as protected_bytes,
                SUM(CASE WHEN fv.id IS NULL AND fs.is_ignored = 0 THEN fs.size ELSE 0 END) as vulnerable_bytes
            FROM filesystem_state fs
            LEFT JOIN (SELECT DISTINCT filesystem_state_id as id FROM file_versions) fv ON fv.id = fs.id
            WHERE fs.file_path LIKE :prefix
        """)
        stats = db.execute(stats_sql, {"prefix": f"{prefix}%"}).fetchone()
        root_stats.append(
            {"root": root, "protected": stats[0] or 0, "vulnerable": stats[1] or 0}
        )

    # 3. Extension Breakdown (Top 15)
    ext_sql = text("""
        SELECT
            LOWER(REPLACE(file_path, RTRIM(file_path, REPLACE(file_path, '.', '')), '')) as ext,
            SUM(size) as total_size,
            COUNT(*) as count
        FROM filesystem_state
        WHERE file_path LIKE '%.%'
        GROUP BY ext
        ORDER BY total_size DESC
        LIMIT 15
    """)
    exts = db.execute(ext_sql).fetchall()

    # 4. Data Aging (Heatmap)
    now = datetime.now(timezone.utc).timestamp()
    one_year = 365 * 24 * 60 * 60
    aging_sql = text(f"""
        SELECT
            CASE
                WHEN mtime > {now - one_year} THEN 'Recent (< 1yr)'
                WHEN mtime > {now - (2 * one_year)} THEN 'Warm (1-2yrs)'
                WHEN mtime > {now - (5 * one_year)} THEN 'Cold (2-5yrs)'
                ELSE 'Frozen (> 5yrs)'
            END as bucket,
            SUM(size) as total_size
        FROM filesystem_state
        GROUP BY bucket
    """)
    aging = db.execute(aging_sql).fetchall()

    # 5. Redundancy (Copies per file)
    redundancy_sql = text("""
        SELECT
            copy_count,
            COUNT(*) as file_count,
            SUM(size) as total_size
        FROM (
            SELECT fs.size, COUNT(fv.id) as copy_count
            FROM filesystem_state fs
            LEFT JOIN file_versions fv ON fv.filesystem_state_id = fs.id
            WHERE fs.is_ignored = 0
            GROUP BY fs.id
        )
        GROUP BY copy_count
    """)
    redundancy = db.execute(redundancy_sql).fetchall()

    return {
        "summary": {
            "total_bytes": dedupe[0] or 0,
            "unique_bytes": dedupe[2] or 0,
            "total_files": dedupe[1] or 0,
        },
        "roots": root_stats,
        "extensions": [{"ext": e[0], "size": e[1], "count": e[2]} for e in exts],
        "aging": [{"bucket": a[0], "size": a[1]} for a in aging],
        "redundancy": [
            {"copies": r[0], "file_count": r[1], "size": r[2]} for r in redundancy
        ],
    }


@router.get("/browse", response_model=List[FileItemSchema])
def browse_index(
    path: Optional[str] = None,
    include_ignored: bool = False,
    db: Session = Depends(get_db),
):
    roots = get_source_roots(db)
    if path is None or path == "ROOT":
        # OPTIMIZED: Fetch all root stats in a single complex SQL aggregate
        results = []
        for root in roots:
            prefix = root if root.endswith("/") else root + "/"
            stats_sql = text("""
                SELECT
                    MAX(CASE WHEN fv.id IS NULL AND fs.is_ignored = 0 THEN 1 ELSE 0 END) as is_vulnerable,
                    COUNT(DISTINCT CASE WHEN fv.id IS NOT NULL THEN fs.id END) as restorable_count,
                    COUNT(DISTINCT CASE WHEN fv.id IS NOT NULL AND rc.id IS NOT NULL THEN fs.id END) as queued_count
                FROM filesystem_state fs
                LEFT JOIN file_versions fv ON fv.filesystem_state_id = fs.id
                LEFT JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
                WHERE fs.file_path LIKE :prefix
            """)
            stats = db.execute(stats_sql, {"prefix": f"{prefix}%"}).fetchone()

            is_vuln = stats[0] if stats else 0
            restorable = stats[1] if stats else 0
            queued = stats[2] if stats else 0

            is_selected = restorable > 0 and queued == restorable
            is_indeterminate = 0 < queued < restorable

            results.append(
                FileItemSchema(
                    name=root,
                    path=root,
                    type="directory",
                    size=0,
                    mtime=0,
                    vulnerable=bool(is_vuln),
                    selected=is_selected,
                    indeterminate=is_indeterminate,
                )
            )
        return results

    prefix = path if path.endswith("/") else path + "/"
    ignore_filter = " AND fs.is_ignored = 0" if not include_ignored else ""
    results = []

    # OPTIMIZED: Fetch ALL subdirectory metadata in a SINGLE aggregate query
    # This replaces the N+1 query pattern that was killing performance
    subdir_agg_sql = text(f"""
        SELECT
            SUBSTR(fs.file_path, LENGTH(:prefix) + 1, INSTR(SUBSTR(fs.file_path, LENGTH(:prefix) + 1), '/') - 1) as dirname,
            MAX(CASE WHEN fv.id IS NULL AND fs.is_ignored = 0 THEN 1 ELSE 0 END) as is_vulnerable,
            COUNT(DISTINCT CASE WHEN fv.id IS NOT NULL THEN fs.id END) as restorable_count,
            COUNT(DISTINCT CASE WHEN fv.id IS NOT NULL AND rc.id IS NOT NULL THEN fs.id END) as queued_count
        FROM filesystem_state fs
        LEFT JOIN file_versions fv ON fv.filesystem_state_id = fs.id
        LEFT JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
        WHERE fs.file_path LIKE :search_prefix
        AND SUBSTR(fs.file_path, LENGTH(:prefix) + 1) LIKE '%/%' {ignore_filter}
        GROUP BY dirname
    """)

    subdirs = db.execute(
        subdir_agg_sql, {"prefix": prefix, "search_prefix": f"{prefix}%"}
    ).fetchall()

    for sd in subdirs:
        name = sd[0]
        is_vuln = sd[1]
        restorable = sd[2]
        queued = sd[3]

        is_selected = restorable > 0 and queued == restorable
        is_indeterminate = 0 < queued < restorable

        results.append(
            FileItemSchema(
                name=name,
                path=prefix + name,
                type="directory",
                size=0,
                mtime=0,
                vulnerable=bool(is_vuln),
                selected=is_selected,
                indeterminate=is_indeterminate,
            )
        )

    # OPTIMIZED: Fetch files with version/cart status in a single joined query
    file_sql = text(f"""
        SELECT
            fs.file_path, fs.size, fs.mtime, fs.id,
            MAX(CASE WHEN fv.id IS NOT NULL THEN 1 ELSE 0 END) as has_version,
            MAX(CASE WHEN rc.id IS NOT NULL THEN 1 ELSE 0 END) as is_selected,
            GROUP_CONCAT(DISTINCT sm.identifier) as media_list
        FROM filesystem_state fs
        LEFT JOIN file_versions fv ON fv.filesystem_state_id = fs.id
        LEFT JOIN storage_media sm ON sm.id = fv.media_id
        LEFT JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
        WHERE fs.file_path LIKE :search_prefix
        AND SUBSTR(fs.file_path, LENGTH(:prefix) + 1) NOT LIKE '%/%' {ignore_filter}
        GROUP BY fs.id
    """)

    files = db.execute(
        file_sql, {"prefix": prefix, "search_prefix": f"{prefix}%"}
    ).fetchall()

    for f in files:
        media_list = f[6].split(",") if f[6] else []
        name = f[0].split("/")[-1]
        results.append(
            FileItemSchema(
                name=name,
                path=f[0],
                type="file",
                size=f[1],
                mtime=f[2],
                media=media_list,
                vulnerable=not bool(f[4]),
                selected=bool(f[5]),
            )
        )

    results.sort(key=lambda x: (x.type != "directory", x.name.lower()))
    return results


@router.get("/search", response_model=List[FileItemSchema])
def search_index(q: str, include_ignored: bool = False, db: Session = Depends(get_db)):
    if not q or len(q) < 3:
        return []

    ignore_filter = " AND fs.is_ignored = 0" if not include_ignored else ""

    # Use FTS5 for instantaneous full-text search
    sql = text(f"""
        SELECT
            fs.file_path, fs.size, fs.mtime, fs.id,
            MAX(CASE WHEN fv.id IS NOT NULL THEN 1 ELSE 0 END) as has_version,
            MAX(CASE WHEN rc.id IS NOT NULL THEN 1 ELSE 0 END) as is_selected,
            GROUP_CONCAT(DISTINCT sm.identifier) as media_list
        FROM filesystem_fts
        JOIN filesystem_state fs ON fs.id = filesystem_fts.rowid
        LEFT JOIN file_versions fv ON fv.filesystem_state_id = fs.id
        LEFT JOIN storage_media sm ON sm.id = fv.media_id
        LEFT JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
        WHERE filesystem_fts MATCH :query {ignore_filter}
        GROUP BY fs.id
        LIMIT 200
    """)

    safe_query = f'"{q}"'
    files = db.execute(sql, {"query": safe_query}).fetchall()

    results = []
    for f in files:
        name = f[0].split("/")[-1]
        media_list = f[6].split(",") if f[6] else []

        results.append(
            FileItemSchema(
                name=name,
                path=f[0],
                type="file",
                size=f[1],
                mtime=f[2],
                media=media_list,
                vulnerable=not bool(f[4]),
                selected=bool(f[5]),
            )
        )

    results.sort(key=lambda x: x.name.lower())
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

        is_selected = (
            db.query(models.RestoreCart)
            .filter(models.RestoreCart.filesystem_state_id == file_state.id)
            .first()
            is not None
        )

        return ItemMetadataSchema(
            id=file_state.id,  # Now included
            file_path=file_state.file_path,
            type="file",
            size=file_state.size,
            mtime=file_state.mtime,
            last_seen_timestamp=file_state.last_seen_timestamp,
            sha256_hash=file_state.sha256_hash,
            versions=versions,
            vulnerable=not bool(file_state.versions),
            selected=is_selected,
        )
    prefix = path if path.endswith("/") else path + "/"
    # Check recursive vulnerability and selection
    stats_sql = text("""
        SELECT
            MAX(CASE WHEN fv.id IS NULL AND fs.is_ignored = 0 THEN 1 ELSE 0 END) as is_vulnerable,
            COUNT(DISTINCT CASE WHEN fv.id IS NOT NULL THEN fs.id END) as restorable_count,
            COUNT(DISTINCT CASE WHEN fv.id IS NOT NULL AND rc.id IS NOT NULL THEN fs.id END) as queued_count
        FROM filesystem_state fs
        LEFT JOIN file_versions fv ON fv.filesystem_state_id = fs.id
        LEFT JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
        WHERE fs.file_path LIKE :prefix
    """)
    stats = db.execute(stats_sql, {"prefix": f"{prefix}%"}).fetchone()

    is_vuln = stats[0] if stats else 0
    restorable = stats[1] if stats else 0
    queued = stats[2] if stats else 0

    is_selected = restorable > 0 and queued == restorable
    is_indeterminate = 0 < queued < restorable

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
            vulnerable=bool(is_vuln),
            selected=is_selected,
            indeterminate=is_indeterminate,
        )
    raise HTTPException(status_code=404, detail="Item not found")


@router.get("/")
def list_inventory():
    return []
