from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.api.common import get_source_roots, _validate_path_within_roots
from app.api.schemas import TreeNodeSchema
import os

router = APIRouter(tags=["System"])


@router.get(
    "/tree", response_model=List[TreeNodeSchema], operation_id="filesystem_tree"
)
def get_system_tree(path: Optional[str] = None, db_session: Session = Depends(get_db)):
    """Returns a recursive tree view of the system for configuration."""

    roots = get_source_roots(db_session)
    if path is None or path == "ROOT":
        return [
            TreeNodeSchema(name=root, path=root, has_children=True) for root in roots
        ]

    if not _validate_path_within_roots(path, roots):
        raise HTTPException(
            status_code=403, detail="Path is outside configured source roots"
        )

    results = []
    if os.path.exists(path):
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if entry.is_dir() and not entry.name.startswith("."):
                        results.append(
                            TreeNodeSchema(
                                name=entry.name, path=entry.path, has_children=True
                            )
                        )
        except Exception:
            pass
    results.sort(key=lambda x: x.name.lower())
    return results


# --- Discrepancy Endpoints ---
