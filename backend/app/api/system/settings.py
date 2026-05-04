from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.api.common import SettingSchema
from typing import Dict
from app.db import models

router = APIRouter(tags=["System"])


@router.get("/settings", response_model=Dict[str, str], operation_id="get_settings")
def get_settings(db_session: Session = Depends(get_db)):
    """Retrieves all global system configuration key-value pairs."""
    settings_records = db_session.query(models.SystemSetting).all()
    return {record.key: record.value for record in settings_records}


@router.post("/settings", operation_id="update_settings")
def update_settings(setting_data: SettingSchema, db_session: Session = Depends(get_db)):
    """Updates or creates a global system configuration setting."""
    existing_record = (
        db_session.query(models.SystemSetting)
        .filter(models.SystemSetting.key == setting_data.key)
        .first()
    )
    if existing_record:
        existing_record.value = setting_data.value
    else:
        db_session.add(
            models.SystemSetting(key=setting_data.key, value=setting_data.value)
        )
    db_session.commit()

    # Reload schedules in case scan/archival frequency changed
    if setting_data.key in ["schedule_scan", "schedule_archival"]:
        from app.services.scheduler import scheduler_manager

        scheduler_manager.reload()

    return {"message": "Setting committed."}
