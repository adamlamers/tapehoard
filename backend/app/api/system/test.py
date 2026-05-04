from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db import models
import os

router = APIRouter(tags=["System"])


@router.post("/test/reset", operation_id="reset_test_environment")
def reset_test_environment(db_session: Session = Depends(get_db)):
    """Wipes the database and resets state for E2E testing."""

    if os.environ.get("TAPEHOARD_TEST_MODE") != "true":
        raise HTTPException(status_code=403, detail="Reset only allowed in test mode")

    # Wipe tables
    db_session.query(models.FileVersion).delete()
    db_session.query(models.RestoreCart).delete()
    db_session.query(models.Job).delete()
    db_session.query(models.TrackedSource).delete()
    db_session.query(models.FilesystemState).delete()
    db_session.query(models.StorageMedia).delete()
    # Note: Keep SystemSettings if needed, or wipe them too
    db_session.query(models.SystemSetting).delete()

    db_session.commit()

    # Clear mock hardware dirs if we can find them
    # But usually the test will re-initialize them

    return {"message": "Test environment reset"}
