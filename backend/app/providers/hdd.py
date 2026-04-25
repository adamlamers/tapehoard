import os
import shutil
from typing import Optional, BinaryIO
from .base import AbstractStorageProvider
from loguru import logger


class OfflineHDDProvider(AbstractStorageProvider):
    def __init__(self, mount_base: str = "/mnt/backup_disk"):
        self.mount_base = mount_base

    def get_name(self) -> str:
        return "Offline HDD"

    def identify_media(self) -> Optional[str]:
        """Reads the hidden identifier file from the disk root"""
        id_file = os.path.join(self.mount_base, ".tapehoard_id")
        logger.info(f"HDD Provider: Checking for ID file at: {id_file}")

        if os.path.exists(id_file):
            try:
                with open(id_file, "r") as f:
                    content = f.read().strip()
                    logger.info(
                        f"HDD Provider: Found identifier file. Content: '{content}'"
                    )
                    return content
            except Exception as e:
                logger.error(
                    f"HDD Provider: Failed to read identifier at {id_file}: {e}"
                )
        else:
            logger.warning(f"HDD Provider: Identifier file NOT FOUND at: {id_file}")
            if os.path.exists(self.mount_base):
                try:
                    logger.info(
                        f"HDD Provider: Base directory {self.mount_base} exists. Contents: {os.listdir(self.mount_base)}"
                    )
                except Exception as e:
                    logger.error(f"HDD Provider: Failed to list base dir: {e}")
            else:
                logger.error(
                    f"HDD Provider: Base directory {self.mount_base} DOES NOT EXIST."
                )

        return None

    def initialize_media(self, media_id: str) -> bool:
        """Initializes HDD by writing the .tapehoard_id file"""
        try:
            os.makedirs(self.mount_base, exist_ok=True)
            id_file = os.path.join(self.mount_base, ".tapehoard_id")
            with open(id_file, "w") as f:
                f.write(media_id)
            archive_dir = os.path.join(self.mount_base, "tapehoard_backups", "archives")
            os.makedirs(archive_dir, exist_ok=True)
            logger.info(f"Initialized HDD media {media_id} at {self.mount_base}")
            return True
        except Exception as e:
            logger.error(f"HDD Provider: Failed to initialize media: {e}")
            return False

    def prepare_for_write(self, media_id: str) -> bool:
        """Verifies the disk is mounted and the identifier matches"""
        current_id = self.identify_media()
        if current_id != media_id:
            logger.error(f"Media mismatch. Expected {media_id}, found {current_id}")
            return False

        # Ensure visible data directory exists
        archive_dir = os.path.join(self.mount_base, "tapehoard_backups", "archives")
        os.makedirs(archive_dir, exist_ok=True)
        return True

    def write_archive(self, media_id: str, stream: BinaryIO) -> str:
        """Writes the stream to a new numbered file in a visible folder"""
        archive_dir = os.path.join(self.mount_base, "tapehoard_backups", "archives")

        # Determine next file number
        existing = os.listdir(archive_dir)
        archives = [int(f.split(".")[0]) for f in existing if f.endswith(".tar")]
        next_num = max(archives, default=-1) + 1

        file_name = f"{next_num:06d}.tar"
        target_path = os.path.join(archive_dir, file_name)

        logger.info(f"Writing HDD archive {file_name} to {media_id}")
        with open(target_path, "wb") as f:
            shutil.copyfileobj(stream, f)

        return str(next_num)

    def finalize_media(self, media_id: str):
        """Standard HDD finalization (flush caches)"""
        os.sync()
        logger.info(f"Finalized HDD media {media_id}")

    def read_archive(self, media_id: str, location_id: str) -> BinaryIO:
        file_name = f"{int(location_id):06d}.tar"
        target_path = os.path.join(
            self.mount_base, "tapehoard_backups", "archives", file_name
        )
        if not os.path.exists(target_path):
            raise FileNotFoundError(
                f"Archive {location_id} not found on media {media_id}"
            )
        return open(target_path, "rb")
