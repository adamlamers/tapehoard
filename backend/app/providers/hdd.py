import os
import shutil
from typing import Optional, BinaryIO
from .base import AbstractStorageProvider
from loguru import logger


class OfflineHDDProvider(AbstractStorageProvider):
    """Storage provider for removable hard drives with UUID and signature verification."""

    provider_id = "local_hdd"
    name = "Offline HDD"
    description = "Local or USB-attached block storage devices."
    capabilities = {
        "supports_random_access": True,
        "is_offline_capable": True,
        "supports_hardware_encryption": False,
    }
    config_schema = {
        "mount_path": {
            "type": "string",
            "title": "System Mount Point",
            "description": "The path where the drive is mounted.",
        },
        "device_uuid": {
            "type": "string",
            "title": "Device UUID",
            "description": "Optional UUID to verify the correct drive is mounted.",
        },
    }

    def __init__(
        self, mount_base: str = "/mnt/backup_disk", device_uuid: Optional[str] = None
    ):
        self.mount_base = mount_base
        self.device_uuid = device_uuid

    def get_name(self) -> str:
        return self.name

    def get_live_info(self, force: bool = False) -> dict:
        import psutil

        info = {"online": self.check_online(force=force)}
        if info["online"]:
            try:
                usage = psutil.disk_usage(self.mount_base)
                info["media"] = {
                    "free_bytes": usage.free,
                    "total_bytes": usage.total,
                    "used_bytes": usage.used,
                    "mount_point": self.mount_base,
                }
            except Exception:
                pass
        return info

    def check_online(self, force: bool = False) -> bool:
        """Checks if the HDD mount point is physically accessible and matches UUID if provided."""
        is_accessible = os.path.exists(self.mount_base) and os.path.isdir(
            self.mount_base
        )
        if not is_accessible:
            return False

        if self.device_uuid:
            from app.core.utils import get_path_uuid

            current_uuid = get_path_uuid(self.mount_base)
            if current_uuid and current_uuid != self.device_uuid:
                logger.warning(
                    f"UUID Mismatch at {self.mount_base}. Expected {self.device_uuid}, found {current_uuid}"
                )
                return False

        return True

    def identify_media(self, allow_intrusive=True) -> Optional[str]:
        """Reads the .tapehoard_id file from the root of the HDD."""
        id_file_path = os.path.join(self.mount_base, ".tapehoard_id")
        logger.info(f"HDD Provider: Checking for ID file at: {id_file_path}")

        if not os.path.exists(id_file_path):
            logger.warning(f"HDD Provider: Identity file missing at {id_file_path}")
            return None

        try:
            with open(id_file_path, "r") as f:
                identifier = f.read().strip()
                logger.info(
                    f"HDD Provider: Found identifier file. Content: '{identifier}'"
                )
                return identifier
        except Exception as e:
            logger.error(f"HDD Provider: Failed to read ID file: {e}")
            return None

    def initialize_media(self, media_id: str) -> bool:
        """Prepares the HDD by creating the backup folder structure and identity file."""
        try:
            os.makedirs(self.mount_base, exist_ok=True)

            # Create identity file
            with open(os.path.join(self.mount_base, ".tapehoard_id"), "w") as f:
                f.write(media_id)

            # Create archive folder
            archive_dir = os.path.join(self.mount_base, "tapehoard_backups", "archives")
            os.makedirs(archive_dir, exist_ok=True)

            logger.info(f"HDD {media_id} initialized at {self.mount_base}")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize HDD {media_id}: {e}")
            return False

    def check_existing_data(self) -> bool:
        """Checks if the HDD already has TapeHoard backups."""
        archive_dir = os.path.join(self.mount_base, "tapehoard_backups", "archives")
        if not os.path.exists(archive_dir):
            return False

        # Check for any .tar files
        return any(f.endswith(".tar") for f in os.listdir(archive_dir))

    def prepare_for_write(self, media_id: str) -> bool:
        """Ensures the destination folder is ready for streaming."""
        archive_dir = os.path.join(self.mount_base, "tapehoard_backups", "archives")
        os.makedirs(archive_dir, exist_ok=True)
        return True

    def write_archive(self, media_id: str, stream: BinaryIO) -> str:
        """Writes the stream to a new numbered file, ignoring hidden OS files."""
        archive_dir = os.path.join(self.mount_base, "tapehoard_backups", "archives")

        # Determine next file number by explicitly checking existing .tar volumes
        existing_files = os.listdir(archive_dir)
        archives = []
        for f in existing_files:
            if f.endswith(".tar"):
                try:
                    # Parse the number from '000001.tar'
                    num = int(f.split(".")[0])
                    archives.append(num)
                except (ValueError, IndexError):
                    continue

        next_num = max(archives, default=-1) + 1
        location_id = str(next_num)

        # Use zero-padded naming for clean sorting
        file_name = f"{next_num:06d}.tar"
        target_path = os.path.join(archive_dir, file_name)

        logger.info(f"Writing bitstream to HDD: {target_path}")
        with open(target_path, "wb") as f:
            shutil.copyfileobj(stream, f)

        return location_id

    def read_archive(self, media_id: str, location_id: str) -> BinaryIO:
        """Locates and opens a numbered archive volume."""
        # Standardize on the 6-digit padded format
        file_name = f"{int(location_id):06d}.tar"
        target_path = os.path.join(
            self.mount_base, "tapehoard_backups", "archives", file_name
        )

        if not os.path.exists(target_path):
            # Fallback for older non-padded files if they exist
            legacy_path = os.path.join(
                self.mount_base, "tapehoard_backups", "archives", f"{location_id}.tar"
            )
            if os.path.exists(legacy_path):
                target_path = legacy_path
            else:
                raise FileNotFoundError(
                    f"Archive {location_id} not found on media {media_id} (Checked {target_path})"
                )

        logger.info(f"Opening bitstream from HDD: {target_path}")
        return open(target_path, "rb")

    def finalize_media(self, media_id: str):
        """No special finalization needed for HDD."""
        pass
