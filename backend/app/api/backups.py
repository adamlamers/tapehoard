from fastapi import APIRouter

router = APIRouter(prefix="/backups", tags=["Backups"])


@router.get("/")
def list_backups():
    return []
