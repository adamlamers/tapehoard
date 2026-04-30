import atexit
import os
import shutil
import tempfile
from typing import Any, BinaryIO, Dict, Optional
from loguru import logger

from .base import AbstractStorageProvider

# Track auto-created temp dirs for cleanup at process exit
_auto_temp_dirs: set = set()


def _cleanup_temp_dirs():
    for d in _auto_temp_dirs:
        try:
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass


atexit.register(_cleanup_temp_dirs)


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
            "description": "Path to a directory representing the tape drive (optional — auto-created if omitted)",
            "required": False,
        }
    }

    def __init__(self, config: Dict[str, Any]):
        provided_path = config.get("device_path")
        if provided_path:
            self.device_path: str = provided_path
        else:
            self.device_path = tempfile.mkdtemp(prefix="tapehoard_mock_lto_")
            _auto_temp_dirs.add(self.device_path)
        os.makedirs(self.device_path, exist_ok=True)
        self.mam_path = os.path.join(self.device_path, ".mam")

    def get_name(self) -> str:
        return "Mock LTO Drive"

    def check_online(self, force: bool = False) -> bool:
        return os.path.exists(self.device_path)

    def check_existing_data(self) -> bool:
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
        for item in os.listdir(self.device_path):
            item_path = os.path.join(self.device_path, item)
            if os.path.isfile(item_path):
                os.remove(item_path)
            elif os.path.isdir(item_path):
                shutil.rmtree(item_path)

        with open(self.mam_path, "w") as f:
            f.write(media_id)
        return True

    def prepare_for_write(self, media_id: str) -> bool:
        return self.identify_media() == media_id

    def write_archive(self, media_id: str, stream: BinaryIO) -> str:
        if not self.prepare_for_write(media_id):
            raise Exception("Media mismatch")

        file_num = 0
        while os.path.exists(os.path.join(self.device_path, f"archive_{file_num}.tar")):
            file_num += 1

        file_path = os.path.join(self.device_path, f"archive_{file_num}.tar")

        with open(file_path, "wb") as f:
            shutil.copyfileobj(stream, f)

        return str(file_num)

    def get_utilization(self) -> Optional[float]:
        return 0.1

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
