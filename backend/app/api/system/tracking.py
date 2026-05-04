from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.api.common import BatchTrackRequest
from sqlalchemy import text
from app.db import models

router = APIRouter(tags=["System"])


@router.post("/track/batch", operation_id="batch_track")
def batch_track(request_data: BatchTrackRequest, db_session: Session = Depends(get_db)):
    """Applies bulk inclusion and exclusion rules and synchronizes is_ignored flags."""
    all_paths = list(request_data.tracks) + list(request_data.untracks)
    # Batch-fetch existing TrackedSource records (MEDIUM #15)
    existing_records = (
        db_session.query(models.TrackedSource)
        .filter(models.TrackedSource.path.in_(all_paths))
        .all()
        if all_paths
        else []
    )
    existing_map = {r.path: r for r in existing_records}

    # 1. Update Tracking Rules and set is_ignored = 0 for inclusions
    for path_to_track in request_data.tracks:
        if path_to_track in existing_map:
            existing_map[path_to_track].action = "include"
        else:
            db_session.add(models.TrackedSource(path=path_to_track, action="include"))

        # Mark files as NOT ignored (i.e., Tracked for Archival)
        db_session.execute(
            text(
                "UPDATE filesystem_state SET is_ignored = 0 WHERE file_path = :p OR file_path LIKE :pp"
            ),
            {"p": path_to_track, "pp": f"{path_to_track}/%"},
        )

    # 2. Update Tracking Rules and set is_ignored = 1 for exclusions
    for path_to_untrack in request_data.untracks:
        if path_to_untrack in existing_map:
            existing_map[path_to_untrack].action = "exclude"
        else:
            db_session.add(models.TrackedSource(path=path_to_untrack, action="exclude"))

        # Mark files as IGNORED (i.e., Untracked/Excluded from Archival)
        db_session.execute(
            text(
                "UPDATE filesystem_state SET is_ignored = 1 WHERE file_path = :p OR file_path LIKE :pp"
            ),
            {"p": path_to_untrack, "pp": f"{path_to_untrack}/%"},
        )

    db_session.commit()
    return {"message": "Tracking policy synchronized with filesystem index."}
