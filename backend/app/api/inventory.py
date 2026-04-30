import json
import os
from datetime import datetime, timezone
from typing import List, Optional

import psutil
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.schemas import (
    ItemMetadataSchema,
    MediaCreateSchema,
    MediaSchema,
    MediaUpdateSchema,
    StorageProviderSchema,
    TreeNodeSchema,
)
from app.db import models
from app.db.database import get_db

router = APIRouter(prefix="/inventory", tags=["Inventory & Search"])

# --- Schemas ---


class ReorderMediaRequest(BaseModel):
    media_ids: List[int]


# --- Core Logic ---


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
        "directories": convert_tree_to_list(nested_dir_map, 10),
    }


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


@router.get("/browse")
def browse_archive_index(path: str = "ROOT", db_session: Session = Depends(get_db)):
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
                    SUM(CASE WHEN EXISTS(SELECT 1 FROM restore_cart rc WHERE rc.filesystem_state_id = fs.id) THEN 1 ELSE 0 END) as selected_count
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
            if stats:
                total = stats[0] or 0
                protected = stats[1] or 0
                media_list = stats[2].split(",") if stats[2] else []
                selected_count = stats[3] or 0

            if protected > 0:
                results.append(
                    {
                        "name": root,
                        "path": root,
                        "type": "directory",
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
            SUM(CASE WHEN EXISTS(SELECT 1 FROM restore_cart rc WHERE rc.filesystem_state_id = filesystem_state.id) THEN 1 ELSE 0 END) as selected_count
        FROM filesystem_state
        WHERE file_path LIKE :prefix_wildcard
        AND file_path != :prefix
        AND INSTR(SUBSTR(file_path, LENGTH(:prefix) + 1), '/') > 0
        GROUP BY dir_name
    """)
    dirs = db_session.execute(
        dir_sql, {"prefix": query_path, "prefix_wildcard": f"{query_path}%"}
    ).fetchall()

    # Find files (immediate children) with their media locations
    file_sql = text("""
        SELECT
            fs.id, fs.file_path, fs.size, fs.mtime,
            EXISTS(SELECT 1 FROM file_versions fv WHERE fv.filesystem_state_id = fs.id) as has_version,
            (SELECT GROUP_CONCAT(sm.identifier)
             FROM file_versions fv
             JOIN storage_media sm ON sm.id = fv.media_id
             WHERE fv.filesystem_state_id = fs.id) as media_list,
            EXISTS(SELECT 1 FROM restore_cart rc WHERE rc.filesystem_state_id = fs.id) as is_selected
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

        # Only show directories that have at least one protected file
        if protected == 0:
            continue

        full_dir_path = query_path + d[0]
        results.append(
            {
                "name": d[0],
                "path": full_dir_path,
                "type": "directory",
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


@router.get("/search")
def search_archive_index(
    q: str, path: Optional[str] = None, db_session: Session = Depends(get_db)
):
    """Performs FTS5 search across the indexed file paths, optionally scoped by path."""
    if len(q) < 2:
        return []

    path_filter = ""
    query_params = {"query": q}

    if path and path != "ROOT":
        path_filter = " AND fs.file_path LIKE :path_prefix"
        query_params["path_prefix"] = f"{path}%"

    search_sql = text(
        f"""
        SELECT
            fs.id, fs.file_path, fs.size, fs.mtime,
            EXISTS(SELECT 1 FROM file_versions fv WHERE fv.filesystem_state_id = fs.id) as has_version,
            (SELECT GROUP_CONCAT(sm.identifier)
             FROM file_versions fv
             JOIN storage_media sm ON sm.id = fv.media_id
             WHERE fv.filesystem_state_id = fs.id) as media_list,
            EXISTS(SELECT 1 FROM restore_cart rc WHERE rc.filesystem_state_id = fs.id) as is_selected
        FROM filesystem_fts fts
        JOIN filesystem_state fs ON fs.id = fts.rowid
        WHERE filesystem_fts MATCH :query
        {path_filter}
        ORDER BY rank
        LIMIT 100
    """
    )

    rows = db_session.execute(search_sql, query_params).fetchall()
    return [
        {
            "name": os.path.basename(r[1]),
            "path": r[1],
            "type": "file",
            "size": r[2],
            "mtime": datetime.fromtimestamp(r[3], tz=timezone.utc),
            "vulnerable": False,
            "selected": bool(r[6]),
            "media": r[5].split(",") if r[5] else [],
        }
        for r in rows
        if r[4]  # Only show if has_version is True
    ]


@router.get("/tree", response_model=List[TreeNodeSchema])
def get_archive_tree(path: Optional[str] = None, db_session: Session = Depends(get_db)):
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


@router.get("/metadata", response_model=ItemMetadataSchema)
def get_archive_item_metadata(path: str, db_session: Session = Depends(get_db)):
    """Retrieves full version history and location details for an indexed file."""
    item = (
        db_session.query(models.FilesystemState)
        .filter(models.FilesystemState.file_path == path)
        .first()
    )
    if not item:
        raise HTTPException(status_code=404, detail="File not found in index.")

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

    return ItemMetadataSchema(
        id=item.id,
        path=item.file_path,
        size=item.size,
        mtime=datetime.fromtimestamp(item.mtime, tz=timezone.utc),
        last_seen_timestamp=item.last_seen_timestamp,
        sha256_hash=item.sha256_hash,
        is_ignored=item.is_ignored,
        versions=versions,
    )
