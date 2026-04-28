from abc import ABC, abstractmethod
from typing import Optional, BinaryIO, Dict, Any


class AbstractStorageProvider(ABC):
    # --- Plugin Registration Metadata ---
    provider_id: str = "unknown"
    name: str = "Unknown Provider"
    description: str = ""
    capabilities: Dict[str, bool] = {
        "supports_random_access": False,
        "is_offline_capable": False,
        "supports_hardware_encryption": False,
    }
    config_schema: Dict[str, Any] = {}

    @abstractmethod
    def get_name(self) -> str:
        """Returns the human-readable name of the provider (e.g., 'LTO Tape')"""
        pass

    @abstractmethod
    def check_online(self, force: bool = False) -> bool:
        """Checks if the media is physically present and reachable"""
        pass

    @abstractmethod
    def check_existing_data(self) -> bool:
        """
        Checks if the media already contains TapeHoard data.
        Used to warn users before re-initialization.
        """
        pass

    def get_live_info(self, force: bool = False) -> Dict[str, Any]:
        """
        Standardized method returning hardware telemetry.
        Should return a dict like {"drive": {...}, "media": {...}, "online": bool}
        """
        return {"online": self.check_online(force=force)}

    def get_health_status(self) -> Dict[str, Any]:
        """
        Standardized method returning health status.
        Should return {"status": "HEALTHY"|"WARNING"|"CRITICAL", "alerts": []}
        """
        return {"status": "HEALTHY", "alerts": []}

    @abstractmethod
    def identify_media(self) -> Optional[str]:
        """
        Attempts to read the identifier (barcode/UUID) from the currently inserted media.
        Returns None if no media is inserted or it's unidentifiable.
        """
        pass

    @abstractmethod
    def initialize_media(self, media_id: str) -> bool:
        """
        Initializes raw media by writing the tapehoard identifier/label.
        """
        pass

    @abstractmethod
    def prepare_for_write(self, media_id: str) -> bool:
        """
        Performs any necessary setup (e.g., mounting, winding) before writing.
        Returns True if ready.
        """
        pass

    @abstractmethod
    def write_archive(self, media_id: str, stream: BinaryIO) -> str:
        """
        Writes a tar stream to the media.
        Returns a 'file_number' or 'object_path' used to locate this archive later.
        """
        pass

    @abstractmethod
    def finalize_media(self, media_id: str):
        """Finalizes the media (e.g., writing index, ejecting)"""
        pass

    @abstractmethod
    def read_archive(self, media_id: str, location_id: str) -> BinaryIO:
        """
        Retrieves a specific archive stream from the media.
        """
        pass
