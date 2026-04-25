from abc import ABC, abstractmethod
from typing import Optional, BinaryIO


class AbstractStorageProvider(ABC):
    @abstractmethod
    def get_name(self) -> str:
        """Returns the human-readable name of the provider (e.g., 'LTO Tape')"""
        pass

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
