from typing import Any
from fastapi import APIRouter, Depends, HTTPException
import os
import sqlite3
from datetime import datetime, timezone
from fastapi import BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from app.db.database import get_db

router = APIRouter(tags=["System"])


@router.get("/database/export", operation_id="export_database")
def export_database():
    """Generates a clean backup of the active SQLite database."""
    database_url = os.getenv("DATABASE_URL", "sqlite:///tapehoard.db")
    database_path = database_url.replace("sqlite:///", "")

    if not os.path.exists(database_path):
        database_path = "tapehoard.db"
        if not os.path.exists(database_path):
            raise HTTPException(status_code=404, detail="Index not found.")

    export_temporary_path = "tapehoard_export.db"
    try:
        source_connection = sqlite3.connect(database_path)
        destination_connection = sqlite3.connect(export_temporary_path)
        with destination_connection:
            source_connection.backup(destination_connection)
        source_connection.close()
        destination_connection.close()

        return FileResponse(
            export_temporary_path,
            filename=f"tapehoard_index_{datetime.now(timezone.utc).strftime('%Y%m%d')}.db",
            background=BackgroundTasks().add_task(
                lambda: (
                    os.remove(export_temporary_path)
                    if os.path.exists(export_temporary_path)
                    else None
                )
            ),
        )
    except Exception as export_error:
        if os.path.exists(export_temporary_path):
            os.remove(export_temporary_path)
        raise HTTPException(
            status_code=500, detail=f"Export failed: {str(export_error)}"
        )


@router.post("/database/import", operation_id="import_database")
async def import_database(file: Any, db_session: Session = Depends(get_db)):
    """Overwrites the current system state with an imported index file."""
    # Implementation pending - requires careful session termination
    return {"message": "Import logic restricted for safety."}
