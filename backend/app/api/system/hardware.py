from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.api.common import (
    IgnoreHardwareRequest,
    TapeOperationRequest,
    TapeFileNumberResponse,
    TapeOperationResponse,
)
from app.db import models
import json
import os
from loguru import logger

router = APIRouter(tags=["System"])


@router.get("/hardware/discover", operation_id="discover_hardware")
def discover_hardware(db_session: Session = Depends(get_db)):
    """Polls host hardware and mount points to discover unregistered storage media."""
    discovered_nodes = []

    # If a backup/restore job is active, skip blocking SCSI commands (mt/sg_read_attr
    # retry on "Device or resource busy" for up to 60 s and would stall this endpoint).
    has_active_job = (
        db_session.query(models.Job)
        .filter(
            models.Job.status.in_(["PENDING", "RUNNING"]),
            models.Job.is_cancelled.is_(False),
        )
        .first()
    ) is not None

    # Load Ignore List
    ignored_record = (
        db_session.query(models.SystemSetting)
        .filter(models.SystemSetting.key == "ignored_hardware")
        .first()
    )
    ignore_list = json.loads(ignored_record.value) if ignored_record else []

    # 1. Probe Configured LTO Drives
    drive_record = (
        db_session.query(models.SystemSetting)
        .filter(models.SystemSetting.key == "tape_drives")
        .first()
    )
    if drive_record:
        try:
            device_paths = json.loads(drive_record.value)
            for dev_path in device_paths:
                from app.providers.tape import LTOProvider

                tape_provider = LTOProvider(config={"device_path": dev_path})
                state = (
                    LTOProvider.get_cached_live_info(dev_path)
                    if has_active_job
                    else tape_provider.get_live_info()
                )

                if state["online"]:
                    barcode = state["identity"]
                    if barcode in ignore_list:
                        continue

                    # Check if this tape is already known by barcode OR serial number
                    is_known = False
                    if barcode:
                        is_known = (
                            db_session.query(models.StorageMedia)
                            .filter(models.StorageMedia.identifier == barcode)
                            .first()
                            is not None
                        )

                    mam_info = state["tape"]
                    if not is_known and mam_info.get("serial"):
                        is_known = (
                            db_session.query(models.StorageMedia)
                            .filter(
                                models.StorageMedia.identifier == mam_info["serial"]
                            )
                            .first()
                            is not None
                        )

                    # Get current file number if tape is loaded and no job is active.
                    # Skipped when a job runs because _get_current_file_number() retries
                    # "Device or resource busy" for up to 60 s and would stall discovery.
                    file_number = None
                    if state["tape"] and not has_active_job:
                        try:
                            file_number_str = tape_provider._get_current_file_number()
                            file_number = int(file_number_str)
                        except Exception:
                            pass

                    discovered_nodes.append(
                        {
                            "type": "tape",
                            "device_path": dev_path,
                            "identifier": state["identity"] or "NEW TAPE",
                            "is_registered": is_known,
                            "status": "ready" if not is_known else "active",
                            "hardware_info": {
                                "drive": state["drive"],
                                "tape": state["tape"],
                                "file_number": file_number,
                            },
                        }
                    )
        except Exception as tape_error:
            logger.error(f"Tape discovery failed: {tape_error}")

    # 2. Probe Potential Mount Points
    potential_mounts = ["/mnt", "/media", "/Volumes", os.path.expanduser("~")]
    try:
        root_device_id = os.stat("/").st_dev
    except Exception:
        root_device_id = None

    restore_record = (
        db_session.query(models.SystemSetting)
        .filter(models.SystemSetting.key == "restore_destinations")
        .first()
    )
    restricted_paths = json.loads(restore_record.value) if restore_record else []

    for base_mount in potential_mounts:
        if not os.path.exists(base_mount):
            continue
        try:
            with os.scandir(base_mount) as it:
                for entry in it:
                    if not entry.is_dir():
                        continue

                    if entry.path in restricted_paths or entry.path in ignore_list:
                        continue

                    # Check for TapeHoard signature
                    id_file_path = os.path.join(entry.path, ".tapehoard_id")
                    disk_barcode = None
                    has_signature = os.path.exists(id_file_path)

                    if has_signature:
                        with open(id_file_path, "r") as f:
                            disk_barcode = f.read().strip()
                    else:
                        # Security & System Filtering (only for uninitialized disks to prevent scanning /)
                        try:
                            entry_stats = os.stat(entry.path)
                            if (
                                root_device_id is not None
                                and entry_stats.st_dev == root_device_id
                            ):
                                continue
                        except Exception:
                            continue

                    if disk_barcode in ignore_list:
                        continue
                    is_known = (
                        db_session.query(models.StorageMedia)
                        .filter(models.StorageMedia.identifier == disk_barcode)
                        .first()
                        is not None
                    )

                    if not is_known:
                        # Auto-detect capacity and UUID for HDDs
                        capacity_bytes = None
                        device_uuid = None
                        try:
                            from app.core.utils import get_path_uuid

                            device_uuid = get_path_uuid(entry.path)

                            st = os.statvfs(entry.path)
                            capacity_bytes = st.f_blocks * st.f_frsize
                        except Exception:
                            pass

                        discovered_nodes.append(
                            {
                                "type": "hdd",
                                "mount_path": entry.path,
                                "identifier": disk_barcode or "NEW DISK",
                                "is_registered": False,
                                "status": "uninitialized",
                                "capacity_bytes": capacity_bytes,
                                "device_uuid": device_uuid,
                            }
                        )
        except Exception:
            continue

    return discovered_nodes


@router.post("/hardware/ignore", operation_id="ignore_hardware")
def ignore_hardware(
    request_data: IgnoreHardwareRequest, db_session: Session = Depends(get_db)
):
    """Appends a hardware identifier to the global ignore list."""
    setting_record = (
        db_session.query(models.SystemSetting)
        .filter(models.SystemSetting.key == "ignored_hardware")
        .first()
    )
    if not setting_record:
        setting_record = models.SystemSetting(key="ignored_hardware", value="[]")
        db_session.add(setting_record)

    ignored_items = json.loads(setting_record.value)
    if request_data.identifier not in ignored_items:
        ignored_items.append(request_data.identifier)
        setting_record.value = json.dumps(ignored_items)
        db_session.commit()

    return {"message": "Hardware node ignored."}


def _get_tape_provider(device_path: str, db_session: Session):
    """Helper to get LTOProvider for a device path, validating it exists."""
    drive_record = (
        db_session.query(models.SystemSetting)
        .filter(models.SystemSetting.key == "tape_drives")
        .first()
    )
    if not drive_record:
        raise HTTPException(status_code=400, detail="No tape drives configured")

    try:
        configured_paths = json.loads(drive_record.value)
    except Exception:
        raise HTTPException(status_code=500, detail="Invalid tape drive configuration")

    if device_path not in configured_paths:
        raise HTTPException(
            status_code=400,
            detail=f"Device {device_path} is not a configured tape drive",
        )

    from app.providers.tape import LTOProvider

    return LTOProvider(config={"device_path": device_path})


@router.get(
    "/hardware/tape/file-number",
    operation_id="get_tape_file_number",
    response_model=TapeFileNumberResponse,
)
def get_tape_file_number(device_path: str, db_session: Session = Depends(get_db)):
    """Get the current file number position for a tape drive."""
    provider = _get_tape_provider(device_path, db_session)

    try:
        file_number_str = provider._get_current_file_number()
        file_number = int(file_number_str)
    except Exception as e:
        logger.error(f"Failed to get file number for {device_path}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get file number: {str(e)}"
        )

    return TapeFileNumberResponse(device_path=device_path, file_number=file_number)


@router.post(
    "/hardware/tape/rewind",
    operation_id="rewind_tape",
    response_model=TapeOperationResponse,
)
def rewind_tape(request: TapeOperationRequest, db_session: Session = Depends(get_db)):
    """Rewind a tape to the beginning (BOT)."""
    provider = _get_tape_provider(request.device_path, db_session)

    # Check if any backup/restore job is active
    active_job = (
        db_session.query(models.Job)
        .filter(
            models.Job.status.in_(["PENDING", "RUNNING"]),
            models.Job.is_cancelled.is_(False),
        )
        .first()
    )
    if active_job:
        raise HTTPException(
            status_code=409,
            detail="Cannot perform tape operation while a job is active",
        )

    try:
        provider._run_mt("rewind", timeout_seconds=60)
        return TapeOperationResponse(
            success=True,
            message="Tape rewound to beginning of tape (BOT)",
            device_path=request.device_path,
        )
    except Exception as e:
        logger.error(f"Failed to rewind tape {request.device_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to rewind tape: {str(e)}")


@router.post(
    "/hardware/tape/eject",
    operation_id="eject_tape",
    response_model=TapeOperationResponse,
)
def eject_tape(request: TapeOperationRequest, db_session: Session = Depends(get_db)):
    """Eject (unload/offline) a tape from the drive."""
    provider = _get_tape_provider(request.device_path, db_session)

    # Check if any backup/restore job is active
    active_job = (
        db_session.query(models.Job)
        .filter(
            models.Job.status.in_(["PENDING", "RUNNING"]),
            models.Job.is_cancelled.is_(False),
        )
        .first()
    )
    if active_job:
        raise HTTPException(
            status_code=409,
            detail="Cannot perform tape operation while a job is active",
        )

    try:
        provider._run_mt("offline", timeout_seconds=60)
        return TapeOperationResponse(
            success=True,
            message="Tape ejected from drive",
            device_path=request.device_path,
        )
    except Exception as e:
        logger.error(f"Failed to eject tape {request.device_path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to eject tape: {str(e)}")


@router.post(
    "/hardware/tape/reinitialize",
    operation_id="reinitialize_tape",
    response_model=TapeOperationResponse,
)
def reinitialize_tape(
    request: TapeOperationRequest, db_session: Session = Depends(get_db)
):
    """
    Re-initialize a tape by erasing all data and removing associated archives.
    WARNING: This will permanently delete all data on the tape and remove all
    archive records from the database.
    """
    provider = _get_tape_provider(request.device_path, db_session)

    # Check if any backup/restore job is active
    active_job = (
        db_session.query(models.Job)
        .filter(
            models.Job.status.in_(["PENDING", "RUNNING"]),
            models.Job.is_cancelled.is_(False),
        )
        .first()
    )
    if active_job:
        raise HTTPException(
            status_code=409,
            detail="Cannot perform tape operation while a job is active",
        )

    # Check if tape is write-protected
    if provider.is_write_protected():
        raise HTTPException(status_code=409, detail="Tape is write-protected")

        # Get tape identity before erasing (for file version deletion)
        mam_info = provider.get_mam_info()
        tape_identifier = mam_info.get("barcode") or mam_info.get("serial")
        versions_deleted = 0

        try:
            # Find and delete file versions for this tape
            if tape_identifier:
                media_record = (
                    db_session.query(models.StorageMedia)
                    .filter(models.StorageMedia.identifier == tape_identifier)
                    .first()
                )
                if media_record:
                    # Delete all file versions associated with this media
                    versions = (
                        db_session.query(models.FileVersion)
                        .filter(models.FileVersion.media_id == media_record.id)
                        .all()
                    )
                    versions_deleted = len(versions)
                    for version in versions:
                        db_session.delete(version)
                    logger.info(
                        f"Deleted {versions_deleted} file versions for media {tape_identifier} "
                        f"(id={media_record.id}) during reinitialization"
                    )

            # Erase the tape (this may take a while for full erase)
            provider._run_mt("erase", timeout_seconds=300)
            db_session.commit()
            logger.info(f"Tape {request.device_path} erased for reinitialization")

            msg = "Tape erased successfully"
            if versions_deleted > 0:
                msg += f" and {versions_deleted} file version(s) removed from database"
            msg += ". Use 'Initialize Media' to write a new label."

            return TapeOperationResponse(
                success=True, message=msg, device_path=request.device_path
            )
        except Exception as e:
            db_session.rollback()
            logger.error(f"Failed to reinitialize tape {request.device_path}: {e}")
            raise HTTPException(
                status_code=500, detail=f"Failed to reinitialize tape: {str(e)}"
            )
