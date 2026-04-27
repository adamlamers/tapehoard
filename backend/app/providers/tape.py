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

    def get_drive_info(self) -> dict:
        """Retrieves vendor, model, and firmware version of the tape drive using sg_inq."""
        try:
            # Use sg_inq for reliable SCSI inquiry
            result = subprocess.run(
                ["sg_inq", self.device_path], capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return {}

            info = {}
            for line in result.stdout.splitlines():
                if "Vendor identification:" in line:
                    info["vendor"] = line.split(":", 1)[1].strip()
                elif "Product identification:" in line:
                    info["model"] = line.split(":", 1)[1].strip()
                elif "Product revision level:" in line:
                    info["firmware"] = line.split(":", 1)[1].strip()

            return info
        except Exception as e:
            logger.debug(f"Failed to get drive info for {self.device_path}: {e}")
            return {}

    def get_mam_info(self) -> dict:
        """Reads Media Auxiliary Memory (MAM) attributes using sg_read_attr --raw and parses the binary response."""
        import struct

        try:
            # Use sg_read_attr --raw to get the exact SCSI response buffer
            result = subprocess.run(
                ["sg_read_attr", "--raw", self.device_path],
                capture_output=True,
                timeout=10,
            )

            if result.returncode != 0 or not result.stdout:
                return {}

            data = result.stdout
            if len(data) < 4:
                return {}

            # SCSI READ ATTRIBUTE parameter data starts with a 4-byte length field (Big Endian)
            available_len = struct.unpack(">I", data[:4])[0]
            pos = 4
            end = min(pos + available_len, len(data))

            mam = {}
            # Standard MAM Attribute IDs (SPC-3 / SSC-2 / LTO Specs)
            attr_map = {
                0x0000: "remaining_capacity_mib",
                0x0001: "max_capacity_mib",
                0x0002: "tape_alert_flags",
                0x0003: "load_count",
                0x0220: "lifetime_mib_written",
                0x0221: "lifetime_mib_read",
                0x0222: "session_mib_written",
                0x0223: "session_mib_read",
                0x0400: "manufacturer",
                0x0401: "serial",
                0x0405: "density",
                0x0406: "manufacture_date",
                0x0806: "barcode",
            }

            while pos + 5 <= end:
                # Each attribute header: ID (2), Flags (1), Length (2)
                attr_id, flags, attr_len = struct.unpack(">HBH", data[pos : pos + 5])
                pos += 5
                if pos + attr_len > end:
                    break
                val_bytes = data[pos : pos + attr_len]
                pos += attr_len

                if attr_id in attr_map:
                    key = attr_map[attr_id]
                    # Binary integers (1, 2, 4, or 8 bytes)
                    if attr_id in [
                        0x0000,
                        0x0001,
                        0x0002,
                        0x0003,
                        0x0220,
                        0x0221,
                        0x0222,
                        0x0223,
                    ]:
                        mam[key] = int.from_bytes(val_bytes, "big")
                    elif attr_id == 0x0405:  # Density is a single byte
                        mam[key] = hex(val_bytes[0]) if val_bytes else "0x00"
                    else:
                        try:
                            # Most attributes are ASCII strings
                            val = (
                                val_bytes.decode("ascii", errors="ignore")
                                .split("\x00")[0]
                                .strip()
                            )
                            if val:
                                mam[key] = val
                        except Exception:
                            continue

            # 1. Decode TapeAlerts (Common flags)
            if mam.get("tape_alert_flags"):
                alerts = []
                flags = mam["tape_alert_flags"]
                # Bit indices for common LTO alerts
                alert_map = {
                    3: "Hard Error",
                    4: "Media Error",
                    5: "Read Failure",
                    6: "Write Failure",
                    12: "Media Broken",
                    20: "Clean Now",
                    21: "Clean Periodic",
                    30: "Hardware Failure",
                    31: "Interface Failure",
                }
                for bit, msg in alert_map.items():
                    if (flags >> (64 - bit)) & 1:
                        alerts.append(msg)
                mam["alerts"] = alerts

            # 2. Derive LTO generation from Capacity (the most reliable indicator)
            if "max_capacity_mib" in mam:
                cap = mam["max_capacity_mib"]
                if cap < 150000:
                    mam["generation_label"] = "LTO-1"
                elif cap < 300000:
                    mam["generation_label"] = "LTO-2"
                elif cap < 600000:
                    mam["generation_label"] = "LTO-3"
                elif cap < 1200000:
                    mam["generation_label"] = "LTO-4"
                elif cap < 2000000:
                    mam["generation_label"] = "LTO-5"
                elif cap < 4000000:
                    mam["generation_label"] = "LTO-6"
                elif cap < 10000000:
                    mam["generation_label"] = "LTO-7"
                elif cap < 15000000:
                    mam["generation_label"] = "LTO-8"
                else:
                    mam["generation_label"] = "LTO-9"

            return {k: v for k, v in mam.items() if v}
        except Exception as e:
            logger.debug(f"Failed to read/parse MAM for {self.device_path}: {e}")
            return {}

    def get_name(self) -> str:
        return "LTO Tape"

    def check_online(self) -> bool:
        """Checks if the tape drive is present and READY (or BUSY)"""
        if not os.path.exists(self.device_path):
            return False
        try:
            result = subprocess.run(
                ["mt", "-f", self.device_path, "status"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            # "Device or resource busy" is a success for "is it online"
            if result.returncode != 0 and "Device or resource busy" in result.stderr:
                return True

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
            result = subprocess.run(
                ["mt", "-f", self.device_path, "status"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            import re

            match = re.search(r"File number=(\d+)", result.stdout)
            if match and int(match.group(1)) > 0:
                return True
            return False
        except Exception:
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
            try:
                subprocess.run(
                    ["stenc", "-f", self.device_path, "--off"], capture_output=True
                )
            except Exception:
                pass
            return

        try:
            logger.info(f"Setting LTO hardware encryption key for {self.device_path}")
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

    def identify_media(self, allow_intrusive=True) -> Optional[str]:
        """
        Identifies the tape, using MAM Barcode (0x0806) as the primary and
        most reliable identity to avoid disruptive head movement.
        """
        if not self.check_online():
            return None

        # 1. Try non-intrusive MAM barcode first (FAST and SILENT)
        mam = self.get_mam_info()
        barcode = mam.get("barcode")
        if barcode:
            return barcode

        # 2. If no MAM barcode, try fallback to physical tape label read (SLOW and INTRUSIVE)
        if not allow_intrusive:
            return None
        try:
            self._setup_encryption()
            self._run_mt("rewind")
            result = subprocess.run(
                ["tar", "-xf", self.device_path, "-O", ".tapehoard_label"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception as e:
            logger.debug(f"Physical identification failed for {self.device_path}: {e}")

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

            # 3. Write identifier to MAM chip (Non-intrusive identity)
            try:
                # Use sg_write_attr to set the Barcode attribute (0x0806)
                # Some drives/drivers allow the name, otherwise use the hex ID
                subprocess.run(
                    ["sg_write_attr", "-w", f"0x0806={media_id}", self.device_path],
                    capture_output=True,
                    check=False,  # Don't fail the whole init if MAM write is refused
                )
                logger.info(f"Identity '{media_id}' written to cartridge MAM chip")
            except Exception as mam_err:
                logger.warning(f"Failed to write MAM identity: {mam_err}")

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
            import re

            match = re.search(r"File number=(\d+)", result.stdout)
            if match:
                return match.group(1)

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
