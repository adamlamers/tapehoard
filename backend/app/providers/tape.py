import subprocess
from typing import Optional, BinaryIO, cast
from .base import AbstractStorageProvider
from loguru import logger


class LTOProvider(AbstractStorageProvider):
    def __init__(self, device_path: str = "/dev/nst0"):
        self.device_path = device_path

    def get_name(self) -> str:
        return "LTO Tape"

    def _run_mt(self, command: str):
        try:
            subprocess.run(["mt", "-f", self.device_path, command], check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Tape command 'mt {command}' failed: {e}")
            raise

    def identify_media(self) -> Optional[str]:
        """Reads the label from the beginning of the tape (File Mark 0)"""
        try:
            self._run_mt("rewind")
            # Try to read the label file
            result = subprocess.run(
                ["tar", "-xf", self.device_path, "-O", ".tapehoard_label"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.error(f"Failed to identify tape: {e}")
        return None

    def prepare_for_write(self, media_id: str) -> bool:
        """Fast-forwards to the end of the data to prepare for appending"""
        current_id = self.identify_media()
        if current_id != media_id:
            logger.error(f"Tape mismatch. Expected {media_id}, found {current_id}")
            return False

        # Move to end of data
        self._run_mt("eod")
        return True

    def write_archive(self, media_id: str, stream: BinaryIO) -> str:
        """Writes the stream to tape and returns the file number index"""
        logger.info(f"Streaming archive to LTO {media_id} at current head position")

        proc = subprocess.Popen(
            ["dd", f"of={self.device_path}", "bs=256k"], stdin=subprocess.PIPE
        )

        if proc.stdin:
            # Copy stream to dd stdin
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                proc.stdin.write(chunk)

            proc.stdin.close()

        proc.wait()

        return "unknown"  # To be refined with 'mt status' parsing

    def finalize_media(self, media_id: str):
        self._run_mt("offline")  # Rewind and eject

    def read_archive(self, media_id: str, location_id: str) -> BinaryIO:
        # Seek to FM index
        self._run_mt("rewind")
        try:
            loc_int = int(location_id)
            if loc_int > 0:
                self._run_mt(f"fsf {loc_int}")
        except ValueError:
            pass

        # Return a pipe from dd
        proc = subprocess.Popen(
            ["dd", f"if={self.device_path}", "bs=256k"], stdout=subprocess.PIPE
        )

        if proc.stdout is None:
            raise RuntimeError("Failed to open pipe from dd")

        return cast(BinaryIO, proc.stdout)
