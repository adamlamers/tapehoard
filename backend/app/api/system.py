from fastapi import APIRouter, HTTPException, Depends
import os
from typing import List, Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db import models

router = APIRouter(prefix="/system", tags=["System"])


class FileItemSchema(BaseModel):
    name: str
    path: str
    type: str  # file, directory, link
    size: Optional[int] = None
    mtime: Optional[float] = None
    tracked: bool = False


class TrackToggleRequest(BaseModel):
    path: str
    is_directory: bool = True


@router.get("/browse", response_model=List[FileItemSchema])
def browse_path(path: str = "/source_data", db: Session = Depends(get_db)):
    # If absolute path doesn't exist, try relative to project root
    if not os.path.exists(path):
        local_source = os.path.abspath(os.path.join(os.getcwd(), "..", "source_data"))
        if path == "/source_data" and os.path.exists(local_source):
            path = local_source
        else:
            raise HTTPException(status_code=404, detail=f"Path not found: {path}")

    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail="Path is not a directory")

    # Get all tracked paths to mark items as tracked
    tracked_paths = {t.path for t in db.query(models.TrackedSource).all()}

    results = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                try:
                    stats = entry.stat(follow_symlinks=False)
                    item_type = "file"
                    if entry.is_dir():
                        item_type = "directory"
                    elif entry.is_symlink():
                        item_type = "link"

                    results.append(
                        FileItemSchema(
                            name=entry.name,
                            path=entry.path,
                            type=item_type,
                            size=stats.st_size,
                            mtime=stats.st_mtime,
                            tracked=entry.path in tracked_paths,
                        )
                    )
                except Exception:
                    continue
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Sort: directories first, then name
    results.sort(key=lambda x: (x.type != "directory", x.name.lower()))

    return results


@router.post("/track")
def track_path(req: TrackToggleRequest, db: Session = Depends(get_db)):
    existing = (
        db.query(models.TrackedSource)
        .filter(models.TrackedSource.path == req.path)
        .first()
    )
    if existing:
        return {"message": "Already tracked"}

    new_track = models.TrackedSource(path=req.path, is_directory=req.is_directory)
    db.add(new_track)
    db.commit()
    return {"message": "Path tracked"}


class BatchTrackRequest(BaseModel):
    tracks: List[str] = []  # Paths to track
    untracks: List[str] = []  # Paths to untrack


@router.post("/track/batch")
def track_batch(req: BatchTrackRequest, db: Session = Depends(get_db)):
    # Handle untracks
    if req.untracks:
        db.query(models.TrackedSource).filter(
            models.TrackedSource.path.in_(req.untracks)
        ).delete(synchronize_session=False)

    # Handle tracks
    if req.tracks:
        # Get existing to avoid duplicates
        existing = {
            t.path
            for t in db.query(models.TrackedSource)
            .filter(models.TrackedSource.path.in_(req.tracks))
            .all()
        }
        new_paths = [path for path in req.tracks if path not in existing]

        for path in new_paths:
            # Note: In a real app we'd verify if it's a directory
            new_track = models.TrackedSource(path=path, is_directory=True)
            db.add(new_track)

    db.commit()
    return {
        "message": f"Processed {len(req.tracks)} tracks and {len(req.untracks)} untracks"
    }


class TreeNodeSchema(BaseModel):
    name: str
    path: str
    has_children: bool = False


@router.get("/tree", response_model=List[TreeNodeSchema])
def get_tree(path: str = "/source_data"):
    if not os.path.exists(path):
        local_source = os.path.abspath(os.path.join(os.getcwd(), "..", "source_data"))
        if path == "/source_data" and os.path.exists(local_source):
            path = local_source
        else:
            raise HTTPException(status_code=404, detail="Path not found")

    if not os.path.isdir(path):
        return []

    results = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_dir():
                    # Check if it has subdirectories for the expander icon
                    has_subdirs = False
                    try:
                        with os.scandir(entry.path) as sub_it:
                            for sub_entry in sub_it:
                                if sub_entry.is_dir():
                                    has_subdirs = True
                                    break
                    except Exception:
                        pass

                    results.append(
                        TreeNodeSchema(
                            name=entry.name, path=entry.path, has_children=has_subdirs
                        )
                    )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    results.sort(key=lambda x: x.name.lower())
    return results
