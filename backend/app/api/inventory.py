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


def get_source_roots(db_session: Session) -> List[str]:
    """Retrieves the list of configured source root paths."""
    settings_record = (
        db_session.query(models.SystemSetting)
        .filter(models.SystemSetting.key == "source_roots")
        .first()
    )
    if settings_record:
        try:
            return json.loads(settings_record.value)
        except Exception:
            return [settings_record.value]

    # Defaults
    local_source = os.path.abspath(os.path.join(os.getcwd(), "..", "source_data"))
    if os.path.exists(local_source):
        return [local_source]
    return ["/source_data"]


# --- Request/Response Schemas ---


class FileVersionSchema(BaseModel):
    media_identifier: str
    media_type: str
    file_number: str
    timestamp: datetime


class ItemMetadataSchema(BaseModel):
    id: Optional[int] = None
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
    host_free_bytes: Optional[int] = None
    host_total_bytes: Optional[int] = None

    class Config:
        from_attributes = True


class ReorderMediaRequest(BaseModel):
    media_ids: List[int]


# --- Media Management ---


@router.get("/media", response_model=List[MediaSchema])
def list_storage_media(db_session: Session = Depends(get_db)):
    """Returns all registered storage media with real-time hardware status."""
    from app.services.archiver import archiver_manager

    media_records = (
        db_session.query(models.StorageMedia)
        .order_by(models.StorageMedia.priority_index.asc())
        .all()
    )

    results = []
    for media in media_records:
        extra_config = {}
        if media.extra_config:
            try:
                extra_config = json.loads(media.extra_config)
            except Exception:
                pass

        # Hardware Pulse Check
        hardware_online = False
        hardware_identified = False
        host_free_bytes = None
        host_total_bytes = None

        # Access provider through internal helper
        storage_provider = archiver_manager._get_storage_provider(media)
        if storage_provider:
            hardware_online = storage_provider.check_online()
            if hardware_online:
                detected_id = storage_provider.identify_media()
                hardware_identified = detected_id == media.identifier

            # If not identified by file, try identifying by hardware UUID
            if (
                not hardware_identified
                and media.media_type == "hdd"
                and extra_config.get("device_uuid")
            ):
                from app.core.utils import get_path_uuid

                current_uuid = get_path_uuid(extra_config.get("mount_path"))
                if current_uuid == extra_config.get("device_uuid"):
                    # The path is correct and UUID matches
                    hardware_identified = True
                else:
                    # UUID mismatch or path changed.
                    # Future: scan all mount points for the UUID.
                    pass

            # Fetch host-level stats for HDDs
            if hardware_online and media.media_type == "hdd":
                try:
                    mount_path = extra_config.get("mount_path")
                    if mount_path and os.path.exists(mount_path):
                        st = os.statvfs(mount_path)
                        host_free_bytes = st.f_bavail * st.f_frsize
                        host_total_bytes = st.f_blocks * st.f_frsize
                except Exception:
                    pass

        results.append(
            MediaSchema(
                id=media.id,
                media_type=media.media_type,
                identifier=media.identifier,
                generation_tier=media.generation_tier,
                capacity=media.capacity,
                bytes_used=media.bytes_used,
                location=media.location,
                status=media.status,
                config=extra_config,
                is_online=hardware_online,
                is_identified=hardware_identified,
                priority_index=media.priority_index,
                host_free_bytes=host_free_bytes,
                host_total_bytes=host_total_bytes,
            )
        )
    return results


@router.post("/media/reorder")
def reorder_archival_priority(
    request_data: ReorderMediaRequest, db_session: Session = Depends(get_db)
):
    """Updates the global archival priority order for the media fleet."""
    for index, media_id in enumerate(request_data.media_ids):
        media_record = db_session.get(models.StorageMedia, media_id)
        if media_record:
            media_record.priority_index = index

    db_session.commit()
    return {"message": "Archival priority synchronized."}


@router.post("/media", response_model=MediaSchema)
def register_new_media(
    request_data: MediaCreateSchema, db_session: Session = Depends(get_db)
):
    """Adds a new physical storage medium to the inventory."""
    existing_record = (
        db_session.query(models.StorageMedia)
        .filter(models.StorageMedia.identifier == request_data.identifier)
        .first()
    )
    if existing_record:
        raise HTTPException(status_code=400, detail="Media identifier already in use.")

    media_instance = models.StorageMedia(
        media_type=request_data.media_type,
        identifier=request_data.identifier,
        generation_tier=request_data.generation_tier,
        capacity=request_data.capacity,
        location=request_data.location,
        extra_config=json.dumps(request_data.config),
    )
    db_session.add(media_instance)
    db_session.commit()
    db_session.refresh(media_instance)

    final_config = {}
    if media_instance.extra_config:
        final_config = json.loads(media_instance.extra_config)

    return MediaSchema(
        id=media_instance.id,
        media_type=media_instance.media_type,
        identifier=media_instance.identifier,
        generation_tier=media_instance.generation_tier,
        capacity=media_instance.capacity,
        bytes_used=media_instance.bytes_used,
        location=media_instance.location,
        status=media_instance.status,
        config=final_config,
    )


@router.patch("/media/{media_id}", response_model=MediaSchema)
def update_media_record(
    media_id: int,
    request_data: MediaUpdateSchema,
    db_session: Session = Depends(get_db),
):
    """Updates metadata or configuration for an existing media asset."""
    media_record = db_session.get(models.StorageMedia, media_id)
    if not media_record:
        raise HTTPException(status_code=404, detail="Media asset not found.")

    if request_data.status:
        media_record.status = request_data.status
    if request_data.location:
        media_record.location = request_data.location
    if request_data.config:
        media_record.extra_config = json.dumps(request_data.config)

    db_session.commit()
    db_session.refresh(media_record)

    final_config = {}
    if media_record.extra_config:
        final_config = json.loads(media_record.extra_config)

    return MediaSchema(
        id=media_record.id,
        media_type=media_record.media_type,
        identifier=media_record.identifier,
        generation_tier=media_record.generation_tier,
        capacity=media_record.capacity,
        bytes_used=media_record.bytes_used,
        location=media_record.location,
        status=media_record.status,
        config=final_config,
    )


@router.delete("/media/{media_id}")
def delete_media_asset(media_id: int, db_session: Session = Depends(get_db)):
    """Removes a media asset and all associated version history from the index."""
    media_record = db_session.get(models.StorageMedia, media_id)
    if not media_record:
        raise HTTPException(status_code=404, detail="Media record not found.")

    # Explicit cascade for clarity
    if media_record.versions:
        for version_record in media_record.versions:
            db_session.delete(version_record)

    db_session.delete(media_record)
    db_session.commit()
    return {"message": "Media and associated history successfully purged."}


@router.post("/media/{media_id}/initialize")
def initialize_storage_hardware(
    media_id: int, force: bool = False, db_session: Session = Depends(get_db)
):
    """Prepares hardware for use by the system (wipes and labels media)."""
    from app.services.archiver import archiver_manager

    media_record = db_session.get(models.StorageMedia, media_id)
    if not media_record:
        raise HTTPException(status_code=404, detail="Media record not found.")

    storage_provider = archiver_manager._get_storage_provider(media_record)
    if not storage_provider:
        raise HTTPException(status_code=400, detail="Hardware provider not found.")

    # Safety check for existing backups
    if not force:
        if storage_provider.check_existing_data():
            raise HTTPException(
                status_code=409,
                detail=f"Hardware '{media_record.identifier}' contains existing data. Use 'force' to overwrite.",
            )

    if storage_provider.initialize_media(media_record.identifier):
        return {"message": "Hardware initialization complete."}

    raise HTTPException(
        status_code=500, detail="Hardware refused initialization command."
    )


# --- Browsing & Analytics (Optimized) ---


@router.get("/insights")
def get_system_analytics(db_session: Session = Depends(get_db)):
    """Computes high-signal system metrics with optimized single-pass queries."""

    # 1. Deduplication & Scale
    overall_stats_sql = text("""
        SELECT
            COUNT(*) as total_files,
            SUM(size) as total_size,
            SUM(CASE WHEN is_indexed = 1 THEN size ELSE 0 END) as total_hashed_size,
            (SELECT SUM(min_size) FROM (
                SELECT MIN(size) as min_size
                FROM filesystem_state
                WHERE is_indexed = 1 AND sha256_hash IS NOT NULL
                GROUP BY sha256_hash
            )) as unique_hashed_size
        FROM filesystem_state
    """)
    stats_res = db_session.execute(overall_stats_sql).fetchone()

    total_files = stats_res[0] or 0
    total_size = stats_res[1] or 0
    total_hashed_size = stats_res[2] or 0
    unique_hashed_size = stats_res[3] or 0
    dedupe_savings = total_hashed_size - unique_hashed_size

    # 2. Vulnerability by Root
    source_roots = get_source_roots(db_session)
    root_level_stats = []
    for root_path in source_roots:
        path_prefix = root_path if root_path.endswith("/") else root_path + "/"
        protection_sql = text("""
            SELECT
                SUM(CASE WHEN has_version = 1 THEN size ELSE 0 END) as protected_bytes,
                SUM(CASE WHEN has_version = 0 AND is_ignored = 0 THEN size ELSE 0 END) as vulnerable_bytes
            FROM (
                SELECT fs.size, fs.is_ignored, EXISTS(SELECT 1 FROM file_versions fv WHERE fv.filesystem_state_id = fs.id) as has_version
                FROM filesystem_state fs
                WHERE fs.file_path LIKE :prefix
            )
        """)
        protection_stats = db_session.execute(
            protection_sql, {"prefix": f"{path_prefix}%"}
        ).fetchone()
        root_level_stats.append(
            {
                "root": root_path,
                "protected": protection_stats[0] or 0,
                "vulnerable": protection_stats[1] or 0,
            }
        )

    # 3. Extension Breakdown (Top 10)
    extension_analysis_sql = text("""
        SELECT
            CASE WHEN INSTR(file_path, '.') > 0
                 THEN LOWER(SUBSTR(file_path, INSTR(file_path, '.') + 1))
                 ELSE 'no ext' END as file_extension,
            SUM(size) as total_bytes
        FROM filesystem_state
        GROUP BY file_extension
        ORDER BY total_bytes DESC
        LIMIT 10
    """)
    extension_stats = db_session.execute(extension_analysis_sql).fetchall()

    # 4. Data Aging
    current_unix_time = datetime.now(timezone.utc).timestamp()
    one_year_seconds = 365 * 24 * 60 * 60
    aging_heatmap_sql = text(f"""
        SELECT
            CASE
                WHEN mtime > {current_unix_time - one_year_seconds} THEN 'Recent'
                WHEN mtime > {current_unix_time - (2 * one_year_seconds)} THEN 'Warm'
                WHEN mtime > {current_unix_time - (5 * one_year_seconds)} THEN 'Cold'
                ELSE 'Frozen'
            END as age_category,
            SUM(size) as byte_volume
        FROM filesystem_state
        GROUP BY age_category
    """)
    aging_stats = db_session.execute(aging_heatmap_sql).fetchall()

    # 5. Redundancy status
    redundancy_distribution_sql = text("""
        SELECT
            copies,
            COUNT(*) as unique_objects,
            SUM(size) as total_volume
        FROM (
            SELECT fs.size, (SELECT COUNT(*) FROM file_versions fv WHERE fv.filesystem_state_id = fs.id) as copies
            FROM filesystem_state fs
            WHERE fs.is_ignored = 0
        )
        GROUP BY copies
    """)
    redundancy_stats = db_session.execute(redundancy_distribution_sql).fetchall()

    # 6. Top Duplicated Files
    top_duplicates_sql = text("""
        SELECT
            MIN(file_path) as sample_path,
            size,
            COUNT(*) as copy_count,
            (size * (COUNT(*) - 1)) as saved_bytes
        FROM filesystem_state
        WHERE is_indexed = 1 AND sha256_hash IS NOT NULL
        GROUP BY sha256_hash
        HAVING copy_count > 1
        ORDER BY saved_bytes DESC
        LIMIT 10
    """)
    duplicate_offenders = db_session.execute(top_duplicates_sql).fetchall()

    # 7. Recursive Directory Treemap
    directory_aggregation_sql = text("""
        SELECT
            RTRIM(file_path, REPLACE(file_path, '/', '')) as dir_path,
            SUM(size) as byte_total
        FROM filesystem_state
        GROUP BY dir_path
    """)
    all_directories = db_session.execute(directory_aggregation_sql).fetchall()

    # Hierarchical tree construction
    nested_dir_map = {}
    for path_str, size_val in all_directories:
        if not path_str:
            continue
        path_segments = [p for p in path_str.split("/") if p]

        current_node = nested_dir_map
        accumulated_path = ""
        for segment in path_segments:
            if not accumulated_path:
                accumulated_path = (
                    "/" + segment if path_str.startswith("/") else segment
                )
            else:
                accumulated_path += "/" + segment

            if segment not in current_node:
                current_node[segment] = {
                    "size": 0,
                    "children": {},
                    "fullPath": accumulated_path,
                }
            current_node[segment]["size"] += size_val
            current_node = current_node[segment]["children"]

    # Collapse unhelpful single-child roots
    while len(nested_dir_map) == 1:
        root_key = list(nested_dir_map.keys())[0]
        if not nested_dir_map[root_key]["children"]:
            break
        nested_dir_map = nested_dir_map[root_key]["children"]

    def convert_tree_to_list(tree_dict, max_depth, current_depth=0):
        if current_depth >= max_depth:
            return []
        output_list = []
        for key, value in tree_dict.items():
            children_list = convert_tree_to_list(
                value["children"], max_depth, current_depth + 1
            )
            output_list.append(
                {
                    "path": key,
                    "size": value["size"],
                    "fullPath": value["fullPath"],
                    "children": children_list,
                }
            )
        output_list.sort(key=lambda x: x["size"], reverse=True)
        return output_list[:15]

    return {
        "summary": {
            "total_bytes": total_size,
            "unique_bytes": total_size - dedupe_savings,
            "total_files": total_files,
        },
        "roots": root_level_stats,
        "extensions": [
            {"ext": ext[0], "size": ext[1], "count": 0} for ext in extension_stats
        ],
        "aging": [{"bucket": age[0], "size": age[1]} for age in aging_stats],
        "redundancy": [
            {"copies": red[0], "file_count": red[1], "size": red[2]}
            for red in redundancy_stats
        ],
        "duplicates": [
            {"path": dup[0], "size": dup[1], "copies": dup[2], "saved": dup[3]}
            for dup in duplicate_offenders
        ],
        "directories": convert_tree_to_list(nested_dir_map, 3),
    }


@router.get("/browse", response_model=List[FileItemSchema])
def browse_archive_index(
    path: Optional[str] = None,
    include_ignored: bool = False,
    db_session: Session = Depends(get_db),
):
    """Browses the virtual archive index with recursive protection stats."""
    source_roots = get_source_roots(db_session)
    if path is None or path == "ROOT":
        # Root-level aggregate status
        results = []
        for root in source_roots:
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
            stats = db_session.execute(stats_sql, {"prefix": f"{prefix}%"}).fetchone()

            is_vuln = stats[0] if stats else 0
            restorable = stats[1] if stats else 0
            queued = stats[2] if stats else 0

            results.append(
                FileItemSchema(
                    name=root,
                    path=root,
                    type="directory",
                    size=0,
                    mtime=0,
                    vulnerable=bool(is_vuln),
                    selected=(restorable > 0 and queued == restorable),
                    indeterminate=(0 < queued < restorable),
                )
            )
        return results

    prefix = path if path.endswith("/") else path + "/"
    ignore_filter = " AND fs.is_ignored = 0" if not include_ignored else ""
    results = []

    # Aggregated subdirectory metadata (No N+1)
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

    subdirs = db_session.execute(
        subdir_agg_sql, {"prefix": prefix, "search_prefix": f"{prefix}%"}
    ).fetchall()
    for sd in subdirs:
        name, is_v, restorable, queued = sd[0], sd[1], sd[2], sd[3]
        results.append(
            FileItemSchema(
                name=name,
                path=prefix + name,
                type="directory",
                size=0,
                mtime=0,
                vulnerable=bool(is_v),
                selected=(restorable > 0 and queued == restorable),
                indeterminate=(0 < queued < restorable),
            )
        )

    # File retrieval with version status
    file_query_sql = text(f"""
        SELECT
            fs.file_path, fs.size, fs.mtime, fs.id,
            MAX(CASE WHEN fv.id IS NOT NULL THEN 1 ELSE 0 END) as has_version,
            MAX(CASE WHEN rc.id IS NOT NULL THEN 1 ELSE 0 END) as is_selected,
            GROUP_CONCAT(DISTINCT sm.identifier) as media_identifiers
        FROM filesystem_state fs
        LEFT JOIN file_versions fv ON fv.filesystem_state_id = fs.id
        LEFT JOIN storage_media sm ON sm.id = fv.media_id
        LEFT JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
        WHERE fs.file_path LIKE :search_prefix
        AND SUBSTR(fs.file_path, LENGTH(:prefix) + 1) NOT LIKE '%/%' {ignore_filter}
        GROUP BY fs.id
    """)

    files_found = db_session.execute(
        file_query_sql, {"prefix": prefix, "search_prefix": f"{prefix}%"}
    ).fetchall()
    for file_record in files_found:
        media_list = file_record[6].split(",") if file_record[6] else []
        results.append(
            FileItemSchema(
                name=file_record[0].split("/")[-1],
                path=file_record[0],
                type="file",
                size=file_record[1],
                mtime=file_record[2],
                media=media_list,
                vulnerable=not bool(file_record[4]),
                selected=bool(file_record[5]),
            )
        )

    results.sort(key=lambda x: (x.type != "directory", x.name.lower()))
    return results


@router.get("/search", response_model=List[FileItemSchema])
def search_archive_index(
    q: str, include_ignored: bool = False, db_session: Session = Depends(get_db)
):
    """Searches the entire archive index using high-performance FTS5."""
    if not q or len(q) < 3:
        return []

    ignore_filter = " AND fs.is_ignored = 0" if not include_ignored else ""
    fts_sql = text(f"""
        SELECT
            fs.file_path, fs.size, fs.mtime, fs.id,
            MAX(CASE WHEN fv.id IS NOT NULL THEN 1 ELSE 0 END) as has_version,
            MAX(CASE WHEN rc.id IS NOT NULL THEN 1 ELSE 0 END) as is_selected,
            GROUP_CONCAT(DISTINCT sm.identifier) as media_identifiers
        FROM filesystem_fts
        JOIN filesystem_state fs ON fs.id = filesystem_fts.rowid
        LEFT JOIN file_versions fv ON fv.filesystem_state_id = fs.id
        LEFT JOIN storage_media sm ON sm.id = fv.media_id
        LEFT JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
        WHERE filesystem_fts MATCH :query {ignore_filter}
        GROUP BY fs.id
        LIMIT 200
    """)

    matches = db_session.execute(fts_sql, {"query": f'"{q}"'}).fetchall()
    results = []
    for match in matches:
        media_list = match[6].split(",") if match[6] else []
        results.append(
            FileItemSchema(
                name=match[0].split("/")[-1],
                path=match[0],
                type="file",
                size=match[1],
                mtime=match[2],
                media=media_list,
                vulnerable=not bool(match[4]),
                selected=bool(match[5]),
            )
        )

    results.sort(key=lambda x: x.name.lower())
    return results


@router.get("/tree", response_model=List[TreeNodeSchema])
def get_archive_tree(
    path: Optional[str] = None,
    include_ignored: bool = False,
    db_session: Session = Depends(get_db),
):
    """Returns a recursive tree view of the virtual archive index."""
    if path is None or path == "ROOT":
        source_roots = get_source_roots(db_session)
        return [
            TreeNodeSchema(name=root, path=root, has_children=True)
            for root in source_roots
        ]

    prefix = path if path.endswith("/") else path + "/"
    ignore_filter = " AND is_ignored = 0" if not include_ignored else ""
    subdir_sql = text(f"""
        SELECT DISTINCT SUBSTR(file_path, LENGTH(:prefix) + 1, INSTR(SUBSTR(file_path, LENGTH(:prefix) + 1), '/') - 1) as dirname
        FROM filesystem_state
        WHERE file_path LIKE :search_prefix AND SUBSTR(file_path, LENGTH(:prefix) + 1) LIKE '%/%' {ignore_filter}
    """)
    subdirs = db_session.execute(
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
def get_archive_item_metadata(path: str, db_session: Session = Depends(get_db)):
    """Retrieves exhaustive metadata for a specific archive entry."""
    file_record = (
        db_session.query(models.FilesystemState)
        .filter(models.FilesystemState.file_path == path)
        .first()
    )

    if file_record:
        version_history = [
            FileVersionSchema(
                media_identifier=v.media.identifier,
                media_type=v.media.media_type,
                file_number=v.file_number,
                timestamp=file_record.last_seen_timestamp,
            )
            for v in file_record.versions
        ]

        in_cart = (
            db_session.query(models.RestoreCart)
            .filter(models.RestoreCart.filesystem_state_id == file_record.id)
            .first()
            is not None
        )

        return ItemMetadataSchema(
            id=file_record.id,
            file_path=file_record.file_path,
            type="file",
            size=file_record.size,
            mtime=file_record.mtime,
            last_seen_timestamp=file_record.last_seen_timestamp,
            sha256_hash=file_record.sha256_hash,
            versions=version_history,
            vulnerable=not bool(file_record.versions),
            selected=in_cart,
        )

    # Directory Metadata Aggregate
    path_prefix = path if path.endswith("/") else path + "/"
    stats_agg_sql = text("""
        SELECT
            MAX(CASE WHEN fv.id IS NULL AND fs.is_ignored = 0 THEN 1 ELSE 0 END) as is_vulnerable,
            COUNT(DISTINCT CASE WHEN fv.id IS NOT NULL THEN fs.id END) as restorable_count,
            COUNT(DISTINCT CASE WHEN fv.id IS NOT NULL AND rc.id IS NOT NULL THEN fs.id END) as queued_count
        FROM filesystem_state fs
        LEFT JOIN file_versions fv ON fv.filesystem_state_id = fs.id
        LEFT JOIN restore_cart rc ON rc.filesystem_state_id = fs.id
        WHERE fs.file_path LIKE :prefix
    """)
    stats = db_session.execute(stats_agg_sql, {"prefix": f"{path_prefix}%"}).fetchone()

    is_vuln, restorable, queued = (stats[0] or 0), (stats[1] or 0), (stats[2] or 0)

    dir_size_sql = text("""
        SELECT COUNT(*), SUM(size), MAX(mtime), MAX(last_seen_timestamp)
        FROM filesystem_state
        WHERE file_path LIKE :prefix AND is_ignored = 0
    """)
    dir_row = db_session.execute(dir_size_sql, {"prefix": f"{path_prefix}%"}).fetchone()

    if dir_row and dir_row[0] > 0:
        return ItemMetadataSchema(
            file_path=path,
            type="directory",
            size=dir_row[1] or 0,
            mtime=dir_row[2] or 0,
            last_seen_timestamp=dir_row[3] or datetime.now(timezone.utc),
            child_count=dir_row[0],
            vulnerable=bool(is_vuln),
            selected=(restorable > 0 and queued == restorable),
            indeterminate=(0 < queued < restorable),
        )

    raise HTTPException(status_code=404, detail="Archive entry not found.")


@router.get("/")
def get_inventory_status():
    """Reserved for future fleet-level status reporting."""
    return []
