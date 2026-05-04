from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.api.common import IgnoreHardwareRequest
from app.db import models
import json
import os
from loguru import logger

router = APIRouter(tags=["System"])


@router.get("/hardware/discover", operation_id="discover_hardware")
def discover_hardware(db_session: Session = Depends(get_db)):
    """Polls host hardware and mount points to discover unregistered storage media."""
    discovered_nodes = []

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
                state = tape_provider.get_live_info()

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
