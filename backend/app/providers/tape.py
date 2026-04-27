import subprocess
import os
from typing import Optional, BinaryIO, cast
from .base import AbstractStorageProvider
from loguru import logger


class LTOProvider(AbstractStorageProvider):
    def __init__(
        self, device_path: str = "/dev/nst0", encryption_key: Optional[str] = None
    ):
        self.device_path = device_path
        self.encryption_key = encryption_key

    def get_name(self) -> str:
        return "LTO Tape"

    def check_online(self) -> bool:
        """Checks if the tape drive is present and READY"""
        if not os.path.exists(self.device_path):
            return False
        try:
            # mt status returns 0 if drive is ready and tape is loaded
            result = subprocess.run(
                ["mt", "-f", self.device_path, "status"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # Look for "ONLINE" or "READY" in output depending on driver
            is_ready = (
                "ONLINE" in result.stdout
                or "READY" in result.stdout
                or result.returncode == 0
            )
            return is_ready
        except Exception:
            return False

    def is_write_protected(self) -> bool:
        """Checks if the tape is write-protected (read-only)"""
        try:
            result = subprocess.run(
                ["mt", "-f", self.device_path, "status"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # Common indicators of write protection in mt status
            # WR_PROT is common on Linux, 'read-only' on others
            output = result.stdout.upper()
            return (
                "WR_PROT" in output
                or "READ-ONLY" in output
                or "WRITE PROTECT" in output
            )
        except Exception:
            return False

    def check_existing_data(self) -> bool:
        """Checks if the tape has data after the label (file mark 0)"""
        if not self.check_online():
            return False
        try:
            self._run_mt("rewind")
            # Skip the label file (file 0)
            self._run_mt("fsf 1")
            # If we are not at EOT, there is probably data
            result = subprocess.run(
                ["mt", "-f", self.device_path, "status"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # If file number > 0, it means we successfully skipped at least one file
            import re

            match = re.search(r"File number=(\d+)", result.stdout)
            if match and int(match.group(1)) > 0:
                return True
            return False
        except Exception:
            # If we fail to fsf 1, it usually means we hit EOD/EOT right after file 0
            return False

    def _run_mt(self, command: str):
        try:
            subprocess.run(["mt", "-f", self.device_path, command], check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Tape command 'mt {command}' failed: {e}")
            raise

    def _setup_encryption(self):
        """Configures hardware encryption on the drive using stenc"""
        if not self.encryption_key:
            # Explicitly disable encryption if no key provided
            try:
                subprocess.run(
                    ["stenc", "-f", self.device_path, "--off"], capture_output=True
                )
            except Exception:
                pass
            return

        try:
            logger.info(f"Setting LTO hardware encryption key for {self.device_path}")
            # stenc expects a 32-byte hex key (256-bit)
            # We use a pipe to avoid leaving the key in the process list
            proc = subprocess.Popen(
                ["stenc", "-f", self.device_path, "--import", "-k", "-"],
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            _, stderr = proc.communicate(input=self.encryption_key)

            if proc.returncode != 0:
                logger.error(f"Failed to load encryption key: {stderr}")
                raise RuntimeError(f"LTO Encryption Setup Failed: {stderr}")

            # Verify encryption is on
            subprocess.run(["stenc", "-f", self.device_path, "--on"], check=True)
            logger.info("LTO Hardware Encryption ENABLED and LOCKED")

        except Exception as e:
            logger.error(f"Hardware encryption error: {e}")
            raise

    def identify_media(self) -> Optional[str]:
        """Reads the label from the beginning of the tape (File Mark 0)"""
        try:
            # We must set up encryption BEFORE trying to read the label if it's an encrypted tape
            self._setup_encryption()

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

    def initialize_media(self, media_id: str) -> bool:
        """Writes the identifier to File Mark 0 on the tape"""
        try:
            if self.is_write_protected():
                raise PermissionError(
                    f"Hardware '{self.device_path}' is write-protected (read-only mode). Flip the physical switch on the tape."
                )

            self._run_mt("rewind")
            self._run_mt("weof")  # Ensure we are starting clean
            self._run_mt("rewind")

            import tempfile
            import tarfile

            with tempfile.NamedTemporaryFile("w") as tmp_lbl:
                tmp_lbl.write(media_id)
                tmp_lbl.flush()

                with tempfile.NamedTemporaryFile("wb") as tmp_tar:
                    with tarfile.open(tmp_tar.name, "w") as tar:
                        tar.add(tmp_lbl.name, arcname=".tapehoard_label")

                    # Write to tape
                    with open(tmp_tar.name, "rb") as f:
                        proc = subprocess.Popen(
                            ["dd", f"of={self.device_path}", "bs=256k"],
                            stdin=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                        )
                        if proc.stdin:
                            proc.stdin.write(f.read())
                            proc.stdin.close()
                        _, stderr = proc.communicate()

                        if proc.returncode != 0:
                            stderr_text = stderr.decode() if stderr else "Unknown error"
                            if (
                                "Read-only file system" in stderr_text
                                or "Permission denied" in stderr_text
                            ):
                                raise PermissionError(
                                    f"Tape is write-protected: {stderr_text}"
                                )
                            raise RuntimeError(f"dd failed: {stderr_text}")

            self._run_mt("weof")
            self._run_mt("rewind")
            logger.info(f"Initialized LTO tape with label {media_id}")
            return True
        except PermissionError as e:
            logger.error(f"Tape write protection detected: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize tape: {e}")
            return False

    def prepare_for_write(self, media_id: str) -> bool:
        """Fast-forwards to the end of the data to prepare for appending"""
        current_id = self.identify_media()
        if current_id != media_id:
            logger.error(f"Tape mismatch. Expected {media_id}, found {current_id}")
            return False

        # Move to end of data
        self._run_mt("eod")
        return True

    def _get_current_file_number(self) -> str:
        """Parses 'mt status' to get the current tape file position"""
        try:
            result = subprocess.run(
                ["mt", "-f", self.device_path, "status"],
                capture_output=True,
                text=True,
                check=True,
            )
            # mt status output varies by OS/Driver, but usually contains 'File number=X'
            # We look for a line like 'File number=2, block number=0'
            import re

            match = re.search(r"File number=(\d+)", result.stdout)
            if match:
                return match.group(1)

            # Alternative format
            match = re.search(r"file number (\d+)", result.stdout)
            if match:
                return match.group(1)

            logger.warning(
                f"Could not parse file number from mt status: {result.stdout}"
            )
        except Exception as e:
            logger.error(f"Failed to get tape status: {e}")
        return "0"

    def write_archive(self, media_id: str, stream: BinaryIO) -> str:
        """Writes the stream to tape and returns the file number index"""
        logger.info(f"Streaming archive to LTO {media_id} at current head position")

        # Get position BEFORE writing
        file_num = self._get_current_file_number()

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

        # After writing, we should be at the NEXT file mark.
        # But tar/dd usually leaves us at the end of the written data.
        # We'll return the position we started at as the 'location_id'
        return file_num

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
