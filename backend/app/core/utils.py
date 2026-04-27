import subprocess
import os
import sys
from loguru import logger


def get_path_uuid(path: str) -> str | None:
    """Attempts to retrieve a stable hardware/filesystem UUID for a given path."""
    if not os.path.exists(path):
        return None

    try:
        if sys.platform == "darwin":
            # macOS: Use diskutil
            cmd = ["diskutil", "info", path]
            res = subprocess.run(cmd, capture_output=True, text=True)
            for line in res.stdout.splitlines():
                if "Volume UUID:" in line:
                    return line.split(":", 1)[1].strip()

        elif sys.platform.startswith("linux"):
            # Linux: Use lsblk to find device, then get UUID
            # First find the device node for the path
            find_dev = ["df", "--output=source", path]
            dev_res = subprocess.run(find_dev, capture_output=True, text=True)
            lines = dev_res.stdout.splitlines()
            if len(lines) < 2:
                return None

            device_node = lines[1].strip()
            # Get UUID for the device
            cmd = ["lsblk", "-no", "UUID", device_node]
            uuid_res = subprocess.run(cmd, capture_output=True, text=True)
            return uuid_res.stdout.strip() or None

    except Exception as e:
        logger.debug(f"UUID resolution failed for {path}: {e}")

    return None
