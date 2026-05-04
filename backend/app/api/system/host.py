from fastapi import APIRouter, HTTPException
import os
from loguru import logger

router = APIRouter(tags=["System"])


@router.get("/ls", operation_id="list_directories")
def list_directories(path: str = "/"):
    """Lists subdirectories on the host system for UI path selection."""
    if ".." in path:
        raise HTTPException(status_code=403, detail="Path traversal not allowed")
    if not os.path.exists(path) or not os.path.isdir(path):
        return []

    try:
        results = []
        with os.scandir(path) as it:
            for entry in it:
                try:
                    if entry.is_dir() and not entry.name.startswith("."):
                        results.append({"name": entry.name, "path": entry.path})
                except OSError:
                    continue
        results.sort(key=lambda x: x["name"].lower())
        return results
    except Exception as directory_error:
        logger.error(f"Host LS failed for {path}: {directory_error}")
        raise HTTPException(status_code=500, detail=str(directory_error))
