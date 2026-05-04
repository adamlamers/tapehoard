import json
from datetime import datetime, timezone
from typing import List

import psutil
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.archive import get_source_roots
from app.api.schemas import (
    MediaCreateSchema,
    MediaSchema,
    MediaUpdateSchema,
    StorageProviderSchema,
)
from app.db import models
from app.db.database import get_db

router = APIRouter(prefix="/inventory", tags=["Inventory & Search"])

# --- Schemas ---


class ReorderMediaRequest(BaseModel):
    media_ids: List[int]


# --- Core Logic ---


@router.get("/providers", response_model=List[StorageProviderSchema])
def list_storage_providers():
    """Returns a registry of all available storage providers and their configurations."""
    from app.providers.cloud import CloudStorageProvider
    from app.providers.hdd import OfflineHDDProvider
    from app.providers.tape import LTOProvider
    import os

    providers = [LTOProvider, OfflineHDDProvider, CloudStorageProvider]

    if os.environ.get("TAPEHOARD_TEST_MODE") == "true":
        from app.providers.mock import MockLTOProvider

        providers.append(MockLTOProvider)  # ty: ignore[invalid-argument-type]

    return [
        StorageProviderSchema(
            provider_id=p.provider_id,
            name=p.name,
            description=p.description,
            capabilities=p.capabilities,
            config_schema=p.config_schema,
        )
        for p in providers
    ]


@router.get("/media", response_model=List[MediaSchema])
def list_storage_fleet(refresh: bool = False, db_session: Session = Depends(get_db)):
    """Returns all registered media assets with real-time hardware status."""
    from app.services.archiver import archiver_manager

    media_assets = (
        db_session.query(models.StorageMedia)
        .order_by(models.StorageMedia.priority_index.asc())
        .all()
    )
    results = []

    for media in media_assets:
        provider = archiver_manager._get_storage_provider(media)
        is_online = False
        hardware_identified = False
        needs_registration = False
        host_free_bytes = None
        host_total_bytes = None
        live_info = None

        if provider:
            is_online = provider.check_online(force=refresh)
            try:
                # Attempt to identify the media non-intrusively
                # pass allow_intrusive=False if the provider supports it, otherwise default
                import inspect

                if (
                    "allow_intrusive"
                    in inspect.signature(provider.identify_media).parameters
                ):
                    detected_id = provider.identify_media(allow_intrusive=False)
                else:
                    detected_id = provider.identify_media()

                hardware_identified = detected_id == media.identifier

                # Always populate live_info using the unified interface
                live_info = provider.get_live_info(force=refresh)
                needs_registration = live_info.get("needs_registration", False)

                # For HDD providers, also grab host-level capacity if possible
                if is_online and media.media_type == "hdd":
                    from app.providers.hdd import OfflineHDDProvider

                    if isinstance(provider, OfflineHDDProvider):
                        usage = psutil.disk_usage(provider.mount_base)
                        host_free_bytes = usage.free
                        host_total_bytes = usage.total
            except Exception as e:
                logger.debug(f"Error populating live info for {media.identifier}: {e}")

        # Parse config
        final_config = {}
        if media.extra_config:
            try:
                final_config = json.loads(media.extra_config)
            except Exception:
                pass

        results.append(
            MediaSchema(
                id=media.id,
                identifier=media.identifier,
                media_type=media.media_type,
                generation_tier=media.generation_tier,
                capacity=media.capacity,
                bytes_used=media.bytes_used,
                status=media.status,
                location=media.location,
                last_seen=media.last_seen,
                created_at=media.created_at,
                config=final_config,
                is_online=is_online,
                is_identified=hardware_identified,
                needs_registration=needs_registration,
                priority_index=media.priority_index,
                host_free_bytes=host_free_bytes,
                host_total_bytes=host_total_bytes,
                live_info=live_info,
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
        raise HTTPException(status_code=400, detail="Media identifier already exists.")

    new_media = models.StorageMedia(
        identifier=request_data.identifier,
        media_type=request_data.media_type,
        generation_tier=request_data.generation_tier,
        capacity=request_data.capacity,
        location=request_data.location,
        extra_config=json.dumps(request_data.config),
    )
    db_session.add(new_media)
    db_session.commit()
    db_session.refresh(new_media)

    return MediaSchema(
        id=new_media.id,
        identifier=new_media.identifier,
        media_type=new_media.media_type,
        generation_tier=new_media.generation_tier,
        capacity=new_media.capacity,
        bytes_used=new_media.bytes_used,
        created_at=new_media.created_at,
        location=new_media.location,
        status=new_media.status,
        config=request_data.config,
    )


@router.patch("/media/{media_id}", response_model=MediaSchema)
def update_media_asset(
    media_id: int,
    request_data: MediaUpdateSchema,
    db_session: Session = Depends(get_db),
):
    """Updates specific attributes of a media record (e.g. status, location, capacity)."""
    media_record = db_session.get(models.StorageMedia, media_id)
    if not media_record:
        raise HTTPException(status_code=404, detail="Media record not found.")

    if request_data.status:
        media_record.status = request_data.status
        # AUTOMATIC PURGE ON FAILURE
        if request_data.status in ["FAILED", "RETIRED"]:
            db_session.query(models.FileVersion).filter(
                models.FileVersion.media_id == media_id
            ).delete()

    if request_data.location is not None:
        media_record.location = request_data.location

    if request_data.capacity:
        media_record.capacity = request_data.capacity

    if request_data.config:
        current_config = (
            json.loads(media_record.extra_config) if media_record.extra_config else {}
        )
        current_config.update(request_data.config)
        media_record.extra_config = json.dumps(current_config)

    db_session.commit()
    db_session.refresh(media_record)

    final_config = {}
    if media_record.extra_config:
        try:
            final_config = json.loads(media_record.extra_config)
        except Exception:
            pass

    return MediaSchema(
        id=media_record.id,
        identifier=media_record.identifier,
        media_type=media_record.media_type,
        capacity=media_record.capacity,
        bytes_used=media_record.bytes_used,
        created_at=media_record.created_at,
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

    try:
        if storage_provider.initialize_media(media_record.identifier):
            # Persist auto-generated device_path to DB so archiver finds the same dir
            current_config = (
                json.loads(media_record.extra_config)
                if media_record.extra_config
                else {}
            )
            if "device_path" not in current_config:
                current_config["device_path"] = storage_provider.device_path
                media_record.extra_config = json.dumps(current_config)
                db_session.commit()
            return {"message": "Hardware initialization complete."}
    except PermissionError as pe:
        raise HTTPException(status_code=403, detail=str(pe))
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Hardware initialization failed: {str(e)}"
        )

    raise HTTPException(
        status_code=500, detail="Hardware refused initialization command."
    )


# --- Browsing & Analytics (Optimized) ---


@router.get("/insights")
def get_system_analytics(db_session: Session = Depends(get_db)):
    """Computes high-signal system metrics with optimized single-pass queries."""

    # 1. Deduplication & Scale (Only counting unignored files)
    overall_stats_sql = text("""
        SELECT
            COUNT(*) as total_files,
            SUM(size) as total_size,
            SUM(CASE WHEN sha256_hash IS NOT NULL THEN size ELSE 0 END) as total_hashed_size,
            (SELECT SUM(min_size) FROM (
                SELECT MIN(size) as min_size
                FROM filesystem_state
                WHERE sha256_hash IS NOT NULL AND is_ignored = 0
                GROUP BY sha256_hash
            )) as unique_hashed_size
        FROM filesystem_state
        WHERE is_ignored = 0
    """)
    stats_res = db_session.execute(overall_stats_sql).fetchone()

    total_files = stats_res[0] if stats_res and stats_res[0] is not None else 0
    total_size = stats_res[1] if stats_res and stats_res[1] is not None else 0
    total_hashed_size = stats_res[2] if stats_res and stats_res[2] is not None else 0
    unique_hashed_size = stats_res[3] if stats_res and stats_res[3] is not None else 0
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
                "protected": (
                    protection_stats[0]
                    if protection_stats and protection_stats[0] is not None
                    else 0
                ),
                "vulnerable": (
                    protection_stats[1]
                    if protection_stats and protection_stats[1] is not None
                    else 0
                ),
            }
        )

    # 3. Extension Breakdown (Top 10, Unignored Only)
    extension_analysis_sql = text("""
        SELECT
            CASE WHEN INSTR(file_path, '.') > 0
                 THEN LOWER(SUBSTR(file_path, INSTR(file_path, '.') + 1))
                 ELSE 'no ext' END as file_extension,
            SUM(size) as total_bytes
        FROM filesystem_state
        WHERE is_ignored = 0
        GROUP BY file_extension
        ORDER BY total_bytes DESC
        LIMIT 10
    """)
    extension_stats = db_session.execute(extension_analysis_sql).fetchall()

    # 4. Data Aging (Unignored Only)
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
        WHERE is_ignored = 0
        GROUP BY age_category
    """)
    aging_stats = db_session.execute(aging_heatmap_sql).fetchall()

    # 5. Redundancy status (Unignored Only)
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

    vulnerable_bytes = 0
    protected_bytes = 0
    for row in redundancy_stats:
        if row[0] == 0:
            vulnerable_bytes = row[2] or 0
        else:
            protected_bytes += row[2] or 0

    # 6. Top Duplicated Files (Unignored Only)
    top_duplicates_sql = text("""
        SELECT
            MIN(file_path) as sample_path,
            size,
            COUNT(*) as copy_count,
            (size * (COUNT(*) - 1)) as saved_bytes
        FROM filesystem_state
        WHERE sha256_hash IS NOT NULL AND is_ignored = 0
        GROUP BY sha256_hash
        HAVING copy_count > 1
        ORDER BY saved_bytes DESC
        LIMIT 10
    """)
    duplicate_offenders = db_session.execute(top_duplicates_sql).fetchall()

    # 7. Recursive Directory Treemap (Unignored Only)
    directory_aggregation_sql = text("""
        SELECT
            RTRIM(file_path, REPLACE(file_path, '/', '')) as dir_path,
            SUM(size) as byte_total,
            MAX(mtime) as latest_mtime
        FROM filesystem_state
        WHERE is_ignored = 0
        GROUP BY dir_path
    """)
    all_directories = db_session.execute(directory_aggregation_sql).fetchall()

    # Hierarchical tree construction
    nested_dir_map = {}
    for path_str, size_val, mtime_val in all_directories:
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
                    "mtime": 0,
                    "children": {},
                    "fullPath": accumulated_path,
                }
            current_node[segment]["size"] += size_val
            current_node[segment]["mtime"] = max(
                current_node[segment]["mtime"], mtime_val or 0
            )
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
                    "mtime": value["mtime"],
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
            "protected_bytes": protected_bytes,
            "vulnerable_bytes": vulnerable_bytes,
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
    }


@router.get("/directories")
def get_directory_treemap(db_session: Session = Depends(get_db)):
    """Returns directory tree data for treemap visualization."""
    # Directory aggregation - same as insights but only directories
    directory_aggregation_sql = text("""
        SELECT
            RTRIM(file_path, REPLACE(file_path, '/', '')) as dir_path,
            SUM(size) as byte_total,
            MAX(mtime) as latest_mtime
        FROM filesystem_state
        WHERE is_ignored = 0
        GROUP BY dir_path
    """)
    all_directories = db_session.execute(directory_aggregation_sql).fetchall()

    # Hierarchical tree construction
    nested_dir_map = {}
    for path_str, size_val, mtime_val in all_directories:
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
                    "mtime": 0,
                    "children": {},
                    "fullPath": accumulated_path,
                }
            current_node[segment]["size"] += size_val or 0
            current_node[segment]["mtime"] = max(
                current_node[segment]["mtime"], mtime_val or 0
            )
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
                    "mtime": value["mtime"],
                    "fullPath": value["fullPath"],
                    "children": children_list,
                }
            )
        output_list.sort(key=lambda x: x["size"], reverse=True)
        return output_list[:15]

    return convert_tree_to_list(nested_dir_map, 10)


@router.get("/detect")
def detect_unregistered_media(db_session: Session = Depends(get_db)):
    """Scans all configured hardware providers for newly inserted, unregistered media."""
    from app.services.archiver import archiver_manager

    # 1. Get all unique device paths from existing media
    registered_devices = db_session.query(models.StorageMedia.extra_config).all()
    device_paths = set()
    for (cfg_json,) in registered_devices:
        if cfg_json:
            try:
                cfg = json.loads(cfg_json)
                if "device_path" in cfg:
                    device_paths.add(cfg["device_path"])
            except Exception:
                pass

    # 2. Add default paths if not already in the set
    device_paths.add("/dev/nst0")

    detected = []
    for path in device_paths:
        # Create a temporary mock media record to get a provider instance
        mock_media = models.StorageMedia(
            media_type="lto_tape",
            extra_config=json.dumps({"device_path": path, "compression": True}),
        )
        provider = archiver_manager._get_storage_provider(mock_media)
        if provider and provider.check_online(force=True):
            live = provider.get_live_info(force=True)
            if live.get("identity"):
                # Check if this identity is already in the DB
                exists = (
                    db_session.query(models.StorageMedia)
                    .filter(models.StorageMedia.identifier == live["identity"])
                    .first()
                )
                if not exists:
                    detected.append(
                        {
                            "identifier": live["identity"],
                            "media_type": provider.provider_id,
                            "device_path": path,
                            "live_info": live,
                        }
                    )

    return detected
