from fastapi import APIRouter, Depends
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db import models

router = APIRouter(prefix="/inventory", tags=["Inventory"])


class FileItemSchema(BaseModel):
    name: str
    path: str
    type: str
    size: Optional[int] = None
    mtime: Optional[float] = None
    media: List[str] = []  # List of media identifiers this file is on


@router.get("/browse", response_model=List[FileItemSchema])
def browse_index(path: str = "/", db: Session = Depends(get_db)):
    # This is trickier because we store full paths.
    # We need to find all unique "first level" children of the given path.

    if not path.endswith("/"):
        path += "/"

    # Files directly in this path
    # We can use a regex or just string manipulation in SQLite
    # For simplicity, let's get all files starting with path and then parse

    # Query for files that are in this directory
    # A file is in /dir/ if its path starts with /dir/ and doesn't contain another / after that

    # Actually, a better way for a Virtual FS is to query for all paths starting with 'path'
    # and then find the next component.

    all_files = (
        db.query(models.FilesystemState)
        .filter(models.FilesystemState.file_path.like(f"{path}%"))
        .all()
    )

    results_map = {}

    for f in all_files:
        relative = f.file_path[len(path) :]
        if not relative:
            continue

        parts = relative.split("/")
        name = parts[0]
        full_item_path = path + name

        if len(parts) > 1:
            # It's a directory
            if name not in results_map:
                results_map[name] = FileItemSchema(
                    name=name, path=full_item_path, type="directory", size=0, mtime=0
                )
            results_map[name].size += f.size
            if f.mtime > results_map[name].mtime:
                results_map[name].mtime = f.mtime
        else:
            # It's a file
            media_list = [v.media.identifier for v in f.versions]
            results_map[name] = FileItemSchema(
                name=name,
                path=f.file_path,
                type="file",
                size=f.size,
                mtime=f.mtime,
                media=media_list,
            )

    results = list(results_map.values())
    results.sort(key=lambda x: (x.type != "directory", x.name.lower()))

    return results
