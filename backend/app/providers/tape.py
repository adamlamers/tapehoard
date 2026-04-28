import subprocess
import os
import time
from typing import Optional, BinaryIO, cast, Dict, Any, List
import struct
import re
from .base import AbstractStorageProvider
from loguru import logger


class LTOProvider(AbstractStorageProvider):
    # Class-level store for Last Known Good (LKG) hardware state
    # device_path -> { "drive": {}, "mam": {}, "online": bool, "last_check": float }
    _lkg_state: dict = {}

    def __init__(
        self, device_path: str = "/dev/nst0", encryption_key: Optional[str] = None
    ):
        self.device_path = device_path
        self.encryption_key = encryption_key

        # Initialize LKG entry if not exists
        if self.device_path not in LTOProvider._lkg_state:
            LTOProvider._lkg_state[self.device_path] = {
                "drive": {},
                "mam": {},
                "online": False,
                "last_check": 0.0,
            }

    def _log_command(self, cmd: List[str]):
        """Logs the exact command being sent to the hardware."""
        logger.debug(f"HARDWARE CMD: {' '.join(cmd)}")

    def get_drive_info(self) -> dict:
        """Retrieves vendor, model, and firmware version of the tape drive."""
        # Return LKG if already populated (drive hardware never changes)
        if LTOProvider._lkg_state[self.device_path]["drive"]:
            return LTOProvider._lkg_state[self.device_path]["drive"]

        try:
            cmd = ["sg_inq", self.device_path]
            self._log_command(cmd)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                info = {}
                for line in result.stdout.splitlines():
                    if "Vendor identification:" in line:
                        info["vendor"] = line.split(":", 1)[1].strip()
                    elif "Product identification:" in line:
                        info["model"] = line.split(":", 1)[1].strip()
                    elif "Product revision level:" in line:
                        info["firmware"] = line.split(":", 1)[1].strip()

                if info:
                    LTOProvider._lkg_state[self.device_path]["drive"] = info
                    return info
        except Exception as e:
            logger.debug(f"Direct drive inquiry failed for {self.device_path}: {e}")

        return LTOProvider._lkg_state[self.device_path]["drive"]

    def get_mam_info(self, force: bool = False) -> dict:
        """Reads Media Auxiliary Memory (MAM) attributes using sg_read_attr --raw."""
        # Throttle MAM reads to once every 2 seconds unless forced
        now = time.time()
        if not force and (
            now - LTOProvider._lkg_state[self.device_path].get("last_check", 0) < 2.0
        ):
            return LTOProvider._lkg_state[self.device_path]["mam"]

        # Try up to 3 times with a small backoff if the drive is busy
        for attempt in range(3):
            try:
                cmd = ["sg_read_attr", "--raw", self.device_path]
                self._log_command(cmd)
                result = subprocess.run(cmd, capture_output=True, timeout=10)

                if result.returncode == 0 and result.stdout:
                    data = result.stdout
                    if len(data) < 4:
                        continue

                    available_len = struct.unpack(">I", data[:4])[0]
                    pos = 4
                    end = min(pos + available_len, len(data))

                    mam = {}
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
                        attr_id, flags, attr_len = struct.unpack(
                            ">HBH", data[pos : pos + 5]
                        )
                        pos += 5
                        if pos + attr_len > end:
                            break
                        val_bytes = data[pos : pos + attr_len]
                        pos += attr_len

                        if attr_id in attr_map:
                            key = attr_map[attr_id]
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
                            elif attr_id == 0x0405:
                                mam[key] = hex(val_bytes[0]) if val_bytes else "0x00"
                            else:
                                try:
                                    val = (
                                        val_bytes.decode("ascii", errors="ignore")
                                        .split("\x00")[0]
                                        .strip()
                                    )
                                    if val:
                                        mam[key] = val
                                except Exception:
                                    continue

                    if mam.get("tape_alert_flags"):
                        alerts = []
                        f = mam["tape_alert_flags"]
                        alert_map = {
                            3: "Hard Error",
                            4: "Media Error",
                            5: "Read Failure",
                            6: "Write Failure",
                            20: "Clean Now",
                            30: "Hardware Failure",
                        }
                        for bit, msg in alert_map.items():
                            if (f >> (64 - bit)) & 1:
                                alerts.append(msg)
                        mam["alerts"] = alerts

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

                    # 3. Barcode Fallback
                    if not mam.get("barcode") and mam.get("serial"):
                        mam["barcode"] = mam["serial"]

                    # SUCCESS! Update LKG MAM state
                    LTOProvider._lkg_state[self.device_path]["mam"] = mam
                    LTOProvider._lkg_state[self.device_path]["last_check"] = time.time()
                    return mam

                # If we get "Device or resource busy", wait a bit and retry
                stderr_text = (
                    (result.stderr or b"").decode().lower()
                    if isinstance(result.stderr, bytes)
                    else (result.stderr or "").lower()
                )
                if result.returncode != 0 and "busy" in stderr_text:
                    time.sleep(0.2)
                    continue

            except Exception as e:
                logger.debug(
                    f"MAM read attempt {attempt} failed for {self.device_path}: {e}"
                )
                time.sleep(0.1)

        # Return LKG if direct read failed
        return LTOProvider._lkg_state[self.device_path]["mam"]

    def get_live_state(self) -> Dict[str, Any]:
        """Performs a single-pass discovery of all hardware metrics to ensure consistency."""
        self.check_online()
        # Since check_online throttles and sets online/last_check, we follow its lead
        mam = self.get_mam_info()
        drive = self.get_drive_info()

        identity = mam.get("barcode") or mam.get("serial")

        return {
            "online": LTOProvider._lkg_state[self.device_path]["online"],
            "drive": drive,
            "mam": mam,
            "identity": identity,
        }

    def get_name(self) -> str:
        return "LTO Tape"

    def check_online(self) -> bool:
        """Checks if the tape drive is online. Throttled to 2 seconds."""
        if not os.path.exists(self.device_path):
            LTOProvider._lkg_state[self.device_path]["online"] = False
            return False

        # Return LKG if we checked very recently
        now = time.time()
        if now - LTOProvider._lkg_state[self.device_path].get("last_check", 0) < 2.0:
            return LTOProvider._lkg_state[self.device_path]["online"]

        try:
            cmd = ["mt", "-f", self.device_path, "status"]
            self._log_command(cmd)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)

            stderr = result.stderr or ""
            stdout = result.stdout or ""

            # "Device or resource busy" is a success for "is it online"
            if (
                "Device or resource busy" in stderr
                or "Device or resource busy" in stdout
            ):
                LTOProvider._lkg_state[self.device_path]["online"] = True
                return True

            is_online = (
                "ONLINE" in stdout or "READY" in stdout or result.returncode == 0
            )

            # If we transitioned from online -> offline, clear the LKG MAM (tape was likely ejected)
            if LTOProvider._lkg_state[self.device_path]["online"] and not is_online:
                LTOProvider._lkg_state[self.device_path]["mam"] = {}

            LTOProvider._lkg_state[self.device_path]["online"] = is_online
            LTOProvider._lkg_state[self.device_path]["last_check"] = now
            return is_online
        except Exception:
            return LTOProvider._lkg_state[self.device_path]["online"]

    def is_write_protected(self) -> bool:
        """Checks if the tape is write-protected (read-only)"""
        try:
            cmd = ["mt", "-f", self.device_path, "status"]
            self._log_command(cmd)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
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
            cmd = ["mt", "-f", self.device_path, "status"]
            self._log_command(cmd)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            match = re.search(r"File number=(\d+)", result.stdout)
            return bool(match and int(match.group(1)) > 0)
        except Exception:
            return False

    def _run_mt(self, command: str):
        try:
            cmd_parts = command.split()
            full_cmd = ["mt", "-f", self.device_path] + cmd_parts
            self._log_command(full_cmd)
            subprocess.run(full_cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Tape command 'mt {command}' failed: {e.stderr.decode()}")
            raise

    def _setup_encryption(self):
        """Configures hardware encryption on the drive using stenc"""
        if not self.encryption_key:
            try:
                cmd = ["stenc", "-f", self.device_path, "--off"]
                self._log_command(cmd)
                subprocess.run(cmd, capture_output=True)
            except Exception:
                pass
            return

        try:
            logger.info(f"Setting LTO hardware encryption key for {self.device_path}")
            # stenc expects a 32-byte hex key (256-bit)
            # We use a pipe to avoid leaving the key in the process list
            cmd_import = ["stenc", "-f", self.device_path, "--import", "-k", "-"]
            self._log_command(cmd_import)
            proc = subprocess.Popen(
                cmd_import,
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            _, stderr = proc.communicate(input=self.encryption_key)
            if proc.returncode != 0:
                raise RuntimeError(f"LTO Encryption Setup Failed: {stderr}")

            cmd_on = ["stenc", "-f", self.device_path, "--on"]
            self._log_command(cmd_on)
            subprocess.run(cmd_on, check=True, capture_output=True)
            logger.info("LTO Hardware Encryption ENABLED and LOCKED")
        except Exception as e:
            logger.error(f"Hardware encryption error: {e}")
            raise

    def identify_media(self, allow_intrusive=True) -> Optional[str]:
        """Identifies the tape, prioritizing non-intrusive LKG MAM identity."""
        state = self.get_live_state()
        if not state["online"]:
            return None
        if state["identity"]:
            return state["identity"]

        if not allow_intrusive:
            return None

        try:
            self._setup_encryption()
            self._run_mt("rewind")
            cmd = ["tar", "-xf", self.device_path, "-O", ".tapehoard_label"]
            self._log_command(cmd)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if result.returncode == 0:
                label_id = result.stdout.strip()
                # Update LKG with the new barcode so we don't rewind again
                if "barcode" not in LTOProvider._lkg_state[self.device_path]["mam"]:
                    LTOProvider._lkg_state[self.device_path]["mam"]["barcode"] = (
                        label_id
                    )
                return label_id
        except Exception as e:
            logger.debug(f"Physical identification failed for {self.device_path}: {e}")

        return None

    def initialize_media(self, media_id: str) -> bool:
        """Writes the identifier to File Mark 0 and MAM 0x0806"""
        try:
            if self.is_write_protected():
                raise PermissionError("Tape is write-protected.")

            self._run_mt("rewind")
            self._run_mt("weof")
            self._run_mt("rewind")

            import tempfile
            import tarfile

            with tempfile.NamedTemporaryFile("w") as tmp_lbl:
                tmp_lbl.write(media_id)
                tmp_lbl.flush()
                with tempfile.NamedTemporaryFile("wb") as tmp_tar:
                    with tarfile.open(tmp_tar.name, "w") as tar:
                        tar.add(tmp_lbl.name, arcname=".tapehoard_label")
                    with open(tmp_tar.name, "rb") as f:
                        cmd_dd = ["dd", f"of={self.device_path}", "bs=256k"]
                        self._log_command(cmd_dd)
                        proc = subprocess.Popen(
                            cmd_dd,
                            stdin=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                        )
                        if proc.stdin:
                            proc.stdin.write(f.read())
                            proc.stdin.close()
                        _, stderr = proc.communicate()
                        if proc.returncode != 0:
                            raise RuntimeError(f"dd failed: {stderr.decode()}")

            self._run_mt("weof")
            self._run_mt("rewind")

            # Update MAM 0x0806 (Barcode)
            cmd_mam = ["sg_write_attr", "-w", f"0x0806={media_id}", self.device_path]
            self._log_command(cmd_mam)
            subprocess.run(cmd_mam, capture_output=True)

            # Clear LKG so it re-polls fresh next time
            LTOProvider._lkg_state[self.device_path]["mam"] = {}
            logger.info(f"Initialized LTO tape with label {media_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize tape: {e}")
            return False

    def prepare_for_write(self, media_id: str) -> bool:
        """Fast-forwards to the end of the data to prepare for appending"""
        current_id = self.identify_media()
        if current_id != media_id:
            logger.error(f"Tape mismatch. Expected {media_id}, found {current_id}")
            return False
        self._run_mt("eod")
        return True

    def _get_current_file_number(self) -> str:
        """Parses 'mt status' to get the current tape file position"""
        try:
            cmd = ["mt", "-f", self.device_path, "status"]
            self._log_command(cmd)
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            match = re.search(r"(?:File number=|file number )(\d+)", result.stdout)
            if match:
                return match.group(1)
        except Exception:
            pass
        return "0"

    def write_archive(self, media_id: str, stream: BinaryIO) -> str:
        """Writes the stream to tape and returns the file number index"""
        file_num = self._get_current_file_number()
        cmd_dd = ["dd", f"of={self.device_path}", "bs=256k"]
        self._log_command(cmd_dd)
        proc = subprocess.Popen(cmd_dd, stdin=subprocess.PIPE)
        if proc.stdin:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                proc.stdin.write(chunk)
            proc.stdin.close()
        proc.wait()
        return file_num

    def finalize_media(self, media_id: str):
        self._run_mt("offline")

    def read_archive(self, media_id: str, location_id: str) -> BinaryIO:
        self._run_mt("rewind")
        try:
            loc_int = int(location_id)
            if loc_int > 0:
                self._run_mt(f"fsf {loc_int}")
        except ValueError:
            pass
        cmd_dd = ["dd", f"if={self.device_path}", "bs=256k"]
        self._log_command(cmd_dd)
        proc = subprocess.Popen(cmd_dd, stdout=subprocess.PIPE)
        if proc.stdout is None:
            raise RuntimeError("Failed to open dd pipe")
        return cast(BinaryIO, proc.stdout)
