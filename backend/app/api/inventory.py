import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psutil
from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import schemas
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


def _media_to_schema(media: models.StorageMedia, config: Dict[str, Any]) -> MediaSchema:
    """Convert a StorageMedia model to MediaSchema."""
    return MediaSchema(
        id=media.id,
        identifier=media.identifier,
        media_type=media.media_type,
        generation_tier=media.generation_tier,
        capacity=media.capacity,
        bytes_used=media.bytes_used,
        status=media.status,
        location=media.location,
        location_building=media.location_building,
        location_room=media.location_room,
        location_rack=media.location_rack,
        location_slot=media.location_slot,
        last_seen=media.last_seen,
        created_at=media.created_at,
        generation=media.generation,
        worm=media.worm,
        write_protected=media.write_protected,
        compression=media.compression,
        encryption_key_id=media.encryption_key_id,
        cleaning_cartridge=media.cleaning_cartridge,
        drive_model=media.drive_model,
        device_uuid=media.device_uuid,
        is_ssd=media.is_ssd,
        mount_path=media.mount_path,
        filesystem_type=media.filesystem_type,
        connection_interface=media.connection_interface,
        encrypted=media.encrypted,
        provider_template=media.provider_template,
        endpoint_url=media.endpoint_url,
        region=media.region,
        bucket_name=media.bucket_name,
        access_key_id=media.access_key_id,
        secret_access_key_name=media.secret_access_key_name,
        path_style_access=media.path_style_access,
        storage_class=media.storage_class,
        max_part_size_mb=media.max_part_size_mb,
        obfuscate_filenames=media.obfuscate_filenames,
        encryption_secret_name=media.encryption_secret_name,
        config=config,
    )


@router.get(
    "/providers",
    response_model=List[StorageProviderSchema],
    operation_id="list_providers",
)
def list_providers():
    """Returns a registry of all available storage providers and their configurations."""
    import os

    from app.providers.cloud import CloudStorageProvider
    from app.providers.hdd import OfflineHDDProvider
    from app.providers.tape import LTOProvider

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


@router.get("/media", response_model=List[MediaSchema], operation_id="list_media")
def list_media(refresh: bool = False, db_session: Session = Depends(get_db)):
    """Returns all registered media assets with real-time hardware status."""
    from app.services.archiver import archiver_manager

    # Skip live SCSI probes when a backup/restore job is running.  mt/sg_read_attr
    # block on "Device or resource busy" and can take 15+ s per tape, starving the
    # thread pool and making every other page slow.
    has_active_job = (
        db_session.query(models.Job)
        .filter(
            models.Job.status.in_(["PENDING", "RUNNING"]),
            models.Job.is_cancelled.is_(False),
        )
        .first()
    ) is not None

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
            if (
                has_active_job
                and media.media_type == "lto_tape"
                and hasattr(provider, "device_path")
            ):
                # Use cached state — no SCSI commands while drive is busy writing.
                from app.providers.tape import LTOProvider

                live_info = LTOProvider.get_cached_live_info(provider.device_path)
                is_online = live_info["online"]
                identity = live_info.get("identity")
                hardware_identified = bool(identity) and identity == media.identifier
                needs_registration = False
            else:
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
                    logger.debug(
                        f"Error populating live info for {media.identifier}: {e}"
                    )

        # Parse config
        final_config = {}
        if media.extra_config:
            try:
                final_config = json.loads(media.extra_config)
            except Exception:
                pass

        schema = _media_to_schema(media, final_config)
        schema.is_online = is_online
        schema.is_identified = hardware_identified
        schema.needs_registration = needs_registration
        schema.priority_index = media.priority_index
        schema.host_free_bytes = host_free_bytes
        schema.host_total_bytes = host_total_bytes
        schema.live_info = live_info
        results.append(schema)
    return results


@router.post("/media/reorder", operation_id="reorder_media")
def reorder_media(
    request_data: ReorderMediaRequest, db_session: Session = Depends(get_db)
):
    """Updates the global archival priority order for the media fleet."""
    for index, media_id in enumerate(request_data.media_ids):
        media_record = db_session.get(models.StorageMedia, media_id)
        if media_record:
            media_record.priority_index = index

    db_session.commit()
    return {"message": "Archival priority synchronized."}


def _detect_lto_capacity_from_hardware(
    db_session: Session, identifier: str, device_path: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Queries hardware MAM to get actual capacity and generation for a tape.

    Returns a dict with 'capacity' (bytes), 'generation' (str), and 'device_path'
    if the tape is found online, otherwise None.
    """
    from app.providers.tape import LTOProvider

    paths_to_try = []
    if device_path:
        paths_to_try.append(device_path)
    else:
        # Look up configured drives
        drive_record = (
            db_session.query(models.SystemSetting)
            .filter(models.SystemSetting.key == "tape_drives")
            .first()
        )
        if drive_record:
            try:
                paths_to_try = json.loads(drive_record.value)
            except Exception:
                pass

    for path in paths_to_try:
        try:
            provider = LTOProvider(config={"device_path": path})
            if not provider.check_online(force=True):
                continue
            live = provider.get_live_info(force=True)
            if live.get("identity") == identifier:
                mam = live.get("tape", {})
                max_mib = mam.get("max_capacity_mib")
                if max_mib:
                    capacity_bytes = int(max_mib * 1024 * 1024)
                    generation = mam.get("generation_label")
                    return {
                        "capacity": capacity_bytes,
                        "generation": generation,
                        "device_path": path,
                    }
        except Exception as e:
            logger.debug(f"Hardware capacity detection failed for {path}: {e}")

    return None


@router.post("/media", response_model=MediaSchema, operation_id="create_media")
def create_media(
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

    # Auto-detect LTO capacity/generation from hardware if not provided,
    # or validate against hardware if device_path is given.
    detected_info = None
    if request_data.media_type == "lto_tape":
        assert isinstance(request_data, schemas.LtoTapeCreateSchema)
        needs_detection = (
            request_data.capacity is None
            or request_data.capacity == 0
            or request_data.generation is None
            or request_data.device_path is not None
        )
        if needs_detection:
            detected_info = _detect_lto_capacity_from_hardware(
                db_session,
                request_data.identifier,
                request_data.device_path,
            )
            if detected_info:
                logger.info(
                    f"Auto-detected LTO media {request_data.identifier}: "
                    f"capacity={detected_info['capacity']} bytes, "
                    f"generation={detected_info['generation']}"
                )

    capacity = request_data.capacity
    if request_data.media_type == "lto_tape" and detected_info:
        if capacity is None or capacity == 0:
            capacity = detected_info["capacity"]
        elif detected_info["capacity"] > 0:
            if hasattr(request_data, "device_path") and request_data.device_path:
                # Hardware ground truth: when a device_path is explicitly provided,
                # always trust the drive's MAM over any user input to avoid
                # rounding-up errors that would exceed physical capacity.
                if capacity != detected_info["capacity"]:
                    logger.info(
                        f"Overriding provided capacity with hardware-reported "
                        f"capacity for {request_data.identifier} "
                        f"({capacity} -> {detected_info['capacity']} bytes)"
                    )
                    capacity = detected_info["capacity"]
            else:
                # Manual entry safety net: only override if significantly off
                provided_mib = capacity / (1024 * 1024)
                detected_mib = detected_info["capacity"] / (1024 * 1024)
                if abs(provided_mib - detected_mib) / detected_mib > 0.05:
                    logger.warning(
                        f"Provided capacity ({capacity} bytes) for {request_data.identifier} "
                        f"differs from hardware-reported capacity ({detected_info['capacity']} bytes). "
                        f"Using hardware value."
                    )
                    capacity = detected_info["capacity"]

    # Build base media record
    new_media = models.StorageMedia(
        identifier=request_data.identifier,
        media_type=request_data.media_type,
        capacity=capacity,
        location=request_data.location,
        location_building=request_data.location_building,
        location_room=request_data.location_room,
        location_rack=request_data.location_rack,
        location_slot=request_data.location_slot,
    )

    # Type-specific fields
    if request_data.media_type == "lto_tape":
        assert isinstance(request_data, schemas.LtoTapeCreateSchema)
        generation = request_data.generation
        if not generation and detected_info:
            generation = detected_info.get("generation")
        if not generation:
            generation = "Unknown"
        new_media.generation = generation
        new_media.generation_tier = generation
        new_media.worm = request_data.worm
        new_media.write_protected = request_data.write_protected
        new_media.compression = request_data.compression
        new_media.encryption_key_id = request_data.encryption_key_id
        new_media.cleaning_cartridge = request_data.cleaning_cartridge
        new_media.encryption_secret_name = request_data.encryption_secret_name
    elif request_data.media_type == "local_hdd":
        assert isinstance(request_data, schemas.OfflineHddCreateSchema)
        new_media.drive_model = request_data.drive_model
        new_media.device_uuid = request_data.device_uuid
        new_media.is_ssd = request_data.is_ssd
        new_media.mount_path = request_data.mount_path
        new_media.filesystem_type = request_data.filesystem_type
        new_media.connection_interface = request_data.connection_interface
        new_media.encrypted = request_data.encrypted
        new_media.encryption_key_id = request_data.encryption_key_id
        new_media.encryption_secret_name = request_data.encryption_secret_name
    elif request_data.media_type == "s3_compat":
        assert isinstance(request_data, schemas.CloudCreateSchema)
        new_media.provider_template = request_data.provider_template
        new_media.endpoint_url = request_data.endpoint_url
        new_media.region = request_data.region
        new_media.bucket_name = request_data.bucket_name
        new_media.access_key_id = request_data.access_key_id
        new_media.secret_access_key_name = request_data.secret_access_key_name
        new_media.path_style_access = request_data.path_style_access
        new_media.storage_class = request_data.storage_class
        new_media.max_part_size_mb = request_data.max_part_size_mb
        new_media.obfuscate_filenames = request_data.obfuscate_filenames
        new_media.encryption_secret_name = request_data.encryption_secret_name

    db_session.add(new_media)
    db_session.commit()
    db_session.refresh(new_media)

    return _media_to_schema(new_media, {})


@router.patch(
    "/media/{media_id}", response_model=MediaSchema, operation_id="update_media"
)
def update_media(
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
    if request_data.location_building is not None:
        media_record.location_building = request_data.location_building
    if request_data.location_room is not None:
        media_record.location_room = request_data.location_room
    if request_data.location_rack is not None:
        media_record.location_rack = request_data.location_rack
    if request_data.location_slot is not None:
        media_record.location_slot = request_data.location_slot

    if request_data.capacity is not None:
        if request_data.capacity < media_record.bytes_used:
            raise HTTPException(
                status_code=400,
                detail=f"Capacity cannot be less than utilized space ({media_record.bytes_used} bytes).",
            )
        media_record.capacity = request_data.capacity
        # If media was marked as full but now has free space, reactivate it
        if (
            media_record.status == "full"
            and media_record.bytes_used / media_record.capacity < 0.98
        ):
            media_record.status = "active"

    # LTO fields
    if request_data.generation is not None:
        media_record.generation = request_data.generation
        media_record.generation_tier = request_data.generation
    if request_data.worm is not None:
        media_record.worm = request_data.worm
    if request_data.write_protected is not None:
        media_record.write_protected = request_data.write_protected
    if request_data.compression is not None:
        media_record.compression = request_data.compression
    if request_data.encryption_key_id is not None:
        media_record.encryption_key_id = request_data.encryption_key_id
    if request_data.cleaning_cartridge is not None:
        media_record.cleaning_cartridge = request_data.cleaning_cartridge

    # HDD fields
    if request_data.drive_model is not None:
        media_record.drive_model = request_data.drive_model
    if request_data.device_uuid is not None:
        media_record.device_uuid = request_data.device_uuid
    if request_data.is_ssd is not None:
        media_record.is_ssd = request_data.is_ssd
    if request_data.mount_path is not None:
        media_record.mount_path = request_data.mount_path
    if request_data.filesystem_type is not None:
        media_record.filesystem_type = request_data.filesystem_type
    if request_data.connection_interface is not None:
        media_record.connection_interface = request_data.connection_interface
    if request_data.encrypted is not None:
        media_record.encrypted = request_data.encrypted

    # Cloud fields
    if request_data.provider_template is not None:
        media_record.provider_template = request_data.provider_template
    if request_data.endpoint_url is not None:
        media_record.endpoint_url = request_data.endpoint_url
    if request_data.region is not None:
        media_record.region = request_data.region
    if request_data.bucket_name is not None:
        media_record.bucket_name = request_data.bucket_name
    if request_data.access_key_id is not None:
        media_record.access_key_id = request_data.access_key_id
    if request_data.secret_access_key_name is not None:
        media_record.secret_access_key_name = request_data.secret_access_key_name
    if request_data.path_style_access is not None:
        media_record.path_style_access = request_data.path_style_access
    if request_data.storage_class is not None:
        media_record.storage_class = request_data.storage_class
    if request_data.max_part_size_mb is not None:
        media_record.max_part_size_mb = request_data.max_part_size_mb
    if request_data.obfuscate_filenames is not None:
        media_record.obfuscate_filenames = request_data.obfuscate_filenames
    if request_data.encryption_secret_name is not None:
        media_record.encryption_secret_name = request_data.encryption_secret_name

    # Handle legacy extra_config for backward compatibility
    if media_record.extra_config:
        try:
            current_config = json.loads(media_record.extra_config)
            # Migrate any legacy keys to first-class columns if not already set
            if "device_path" in current_config and not media_record.mount_path:
                media_record.mount_path = current_config["device_path"]
            if (
                "encryption_key" in current_config
                and not media_record.encryption_key_id
            ):
                media_record.encryption_key_id = current_config["encryption_key"]
            if (
                "encryption_passphrase" in current_config
                and not media_record.client_side_encryption_passphrase
            ):
                media_record.client_side_encryption_passphrase = current_config[
                    "encryption_passphrase"
                ]
        except Exception:
            pass

    db_session.commit()
    db_session.refresh(media_record)

    final_config = {}
    if media_record.extra_config:
        try:
            final_config = json.loads(media_record.extra_config)
        except Exception:
            pass

    return _media_to_schema(media_record, final_config)


@router.delete("/media/{media_id}", operation_id="delete_media")
def delete_media(media_id: int, db_session: Session = Depends(get_db)):
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


@router.post("/media/{media_id}/initialize", operation_id="initialize_media")
def initialize_media(
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
            if media_record.media_type == "s3_compat":
                # Cloud providers don't have device_path
                pass
            else:
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


@router.get("/insights", operation_id="get_analytics")
def get_analytics(db_session: Session = Depends(get_db)):
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


@router.get("/directories", operation_id="get_treemap")
def get_treemap(db_session: Session = Depends(get_db)):
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


@router.get("/detect", operation_id="detect_media")
def detect_media(db_session: Session = Depends(get_db)):
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
