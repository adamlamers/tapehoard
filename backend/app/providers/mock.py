import os
import shutil
from typing import Any, BinaryIO, Dict, Optional
from loguru import logger

from .base import AbstractStorageProvider


class MockLTOProvider(AbstractStorageProvider):
    provider_id = "mock_lto"
    name = "Mock LTO Tape (Test)"
    description = "A simulated tape drive for end-to-end testing."
    capabilities = {
        "supports_random_access": False,
        "is_offline_capable": True,
        "supports_hardware_encryption": False,
    }
    config_schema = {
        "device_path": {
            "type": "string",
            "title": "Mock Directory Path",
            "description": "Path to a directory representing the tape drive (e.g., /tmp/mock_lto)",
            "required": True,
            "default": "/tmp/mock_lto",
        }
    }

    def __init__(self, config: Dict[str, Any]):
        self.device_path = config.get("device_path", "/tmp/mock_lto")
        os.makedirs(self.device_path, exist_ok=True)
        # We store metadata in a .mam file inside the mock directory
        self.mam_path = os.path.join(self.device_path, ".mam")

    def get_name(self) -> str:
        return "Mock LTO Drive"

    def check_online(self, force: bool = False) -> bool:
        # For testing, we consider it online if the directory exists
        return os.path.exists(self.device_path)

    def check_existing_data(self) -> bool:
        # Check if there are archive files in the directory
        if not self.check_online():
            return False
        for f in os.listdir(self.device_path):
            if f.endswith(".tar"):
                return True
        return False

    def identify_media(self, allow_intrusive=True) -> Optional[str]:
        if not os.path.exists(self.mam_path):
            return None
        try:
            with open(self.mam_path, "r") as f:
                return f.read().strip()
        except Exception:
            return None

    def initialize_media(self, media_id: str) -> bool:
        # Clear out the directory
        for item in os.listdir(self.device_path):
            item_path = os.path.join(self.device_path, item)
            if os.path.isfile(item_path):
                os.remove(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)

        # Write the new media_id
        with open(self.mam_path, "w") as f:
            f.write(media_id)
        return True

    def prepare_for_write(self, media_id: str) -> bool:
        return self.identify_media() == media_id

    def write_archive(self, media_id: str, stream: BinaryIO) -> str:
        if not self.prepare_for_write(media_id):
            raise Exception("Media mismatch")

        # Determine the next file number
        file_num = 0
        while os.path.exists(os.path.join(self.device_path, f"archive_{file_num}.tar")):
            file_num += 1

        file_path = os.path.join(self.device_path, f"archive_{file_num}.tar")

        with open(file_path, "wb") as f:
            shutil.copyfileobj(stream, f)

        return str(file_num)

    def get_utilization(self) -> Optional[float]:
        return 0.1  # Mock utilization

    def finalize_media(self, media_id: str):
        logger.info(f"Mock media {media_id} finalized")

    def read_archive(self, media_id: str, location_id: str) -> BinaryIO:
        if self.identify_media() != media_id:
            raise Exception("Media mismatch")

        file_path = os.path.join(self.device_path, f"archive_{location_id}.tar")
        if not os.path.exists(file_path):
            raise Exception(f"Archive {location_id} not found on tape")

        return open(file_path, "rb")

    def get_live_info(self, force: bool = False) -> Dict[str, Any]:
        return {
            "online": self.check_online(force),
            "mam": {"barcode": self.identify_media()},
            "drive": {"vendor": "MOCK", "product": "VIRTUAL LTO"},
        }
