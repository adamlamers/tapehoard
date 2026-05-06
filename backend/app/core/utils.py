import subprocess
import os
import sys
from loguru import logger


def _get_ionice_setting() -> str:
    """Reads the user's preferred I/O scheduling class from settings."""
    try:
        from app.db.database import SessionLocal
        from app.db import models

        with SessionLocal() as db_session:
            record = (
                db_session.query(models.SystemSetting)
                .filter(models.SystemSetting.key == "ionice_level")
                .first()
            )
            if record and record.value in ("idle", "best-effort", "realtime"):
                return record.value
    except Exception:
        pass
    return "idle"  # Default: be the most polite


def set_process_priority(level: str):
    """Adjusts CPU and I/O priority of the current process.

    Args:
        level: "background" for lowest priority (ionice idle + nice 19),
               "normal" to reset (ionice best-effort + nice 0).
    """
    try:
        import psutil

        p = psutil.Process(os.getpid())
        if level == "background":
            ionice_level = _get_ionice_setting()
            if hasattr(p, "ionice"):
                if ionice_level == "idle":
                    p.ionice(psutil.IOPRIO_CLASS_IDLE)  # type: ignore[attr-defined]
                elif ionice_level == "realtime":
                    p.ionice(psutil.IOPRIO_CLASS_RT)  # type: ignore[attr-defined]
                else:
                    p.ionice(psutil.IOPRIO_CLASS_BE)  # type: ignore[attr-defined]
            p.nice(19)
        else:
            if hasattr(p, "ionice"):
                p.ionice(psutil.IOPRIO_CLASS_BE)  # type: ignore[attr-defined]
            p.nice(0)
    except Exception as e:
        logger.debug(f"Could not set process priority to '{level}': {e}")


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
