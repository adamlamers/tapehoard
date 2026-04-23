from fastapi import APIRouter, HTTPException, Depends
from typing import List
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db import models

router = APIRouter(prefix="/restores", tags=["Restores"])

# --- Schemas ---


class CartItemSchema(BaseModel):
    id: int
    file_path: str
    size: int
    media_identifiers: List[str]

    class Config:
        from_attributes = True


class ManifestMediaRequirement(BaseModel):
    identifier: str
    media_type: str
    file_count: int
    total_size: int


class RestoreManifestSchema(BaseModel):
    total_files: int
    total_size: int
    media_required: List[ManifestMediaRequirement]


class DirectoryCartRequest(BaseModel):
    path: str


# --- Endpoints ---


@router.get("/cart", response_model=List[CartItemSchema])
def list_cart(db: Session = Depends(get_db)):
    items = db.query(models.RestoreCart).all()
    results = []
    for item in items:
        media_ids = [v.media.identifier for v in item.file_state.versions]
        results.append(
            CartItemSchema(
                id=item.id,
                file_path=item.file_state.file_path,
                size=item.file_state.size,
                media_identifiers=media_ids,
            )
        )
    return results


@router.post("/cart/{file_id}")
def add_to_cart(file_id: int, db: Session = Depends(get_db)):
    existing = (
        db.query(models.RestoreCart)
        .filter(models.RestoreCart.filesystem_state_id == file_id)
        .first()
    )
    if existing:
        return {"message": "Already in cart"}

    file_state = db.query(models.FilesystemState).get(file_id)
    if not file_state or not file_state.versions:
        raise HTTPException(status_code=400, detail="File has no backed up versions")

    new_item = models.RestoreCart(filesystem_state_id=file_id)
    db.add(new_item)
    db.commit()
    return {"message": "Added to cart"}


@router.post("/cart/directory")
def add_directory_to_cart(req: DirectoryCartRequest, db: Session = Depends(get_db)):
    prefix = req.path if req.path.endswith("/") else req.path + "/"

    # Find all files under this path that have at least one version
    eligible_files = (
        db.query(models.FilesystemState)
        .filter(
            models.FilesystemState.file_path.like(f"{prefix}%"),
            models.FilesystemState.versions.any(),
        )
        .all()
    )

    if not eligible_files:
        raise HTTPException(
            status_code=404, detail="No restorable files found in this directory"
        )

    # Get current cart to avoid duplicates
    in_cart = {c.filesystem_state_id for c in db.query(models.RestoreCart).all()}

    added_count = 0
    for f in eligible_files:
        if f.id not in in_cart:
            db.add(models.RestoreCart(filesystem_state_id=f.id))
            added_count += 1

    db.commit()
    return {"message": f"Added {added_count} files from {req.path} to cart"}


@router.delete("/cart/{item_id}")
def remove_from_cart(item_id: int, db: Session = Depends(get_db)):
    item = db.query(models.RestoreCart).get(item_id)
    if item:
        db.delete(item)
        db.commit()
    return {"message": "Removed from cart"}


@router.post("/cart/clear")
def clear_cart(db: Session = Depends(get_db)):
    db.query(models.RestoreCart).delete()
    db.commit()
    return {"message": "Cart cleared"}


@router.get("/manifest", response_model=RestoreManifestSchema)
def get_manifest(db: Session = Depends(get_db)):
    cart_items = db.query(models.RestoreCart).all()
    if not cart_items:
        return RestoreManifestSchema(total_files=0, total_size=0, media_required=[])

    total_size = sum(item.file_state.size for item in cart_items)
    media_map = {}

    for item in cart_items:
        if not item.file_state.versions:
            continue
        primary_v = item.file_state.versions[0]
        ident = primary_v.media.identifier
        m_type = primary_v.media.media_type
        if ident not in media_map:
            media_map[ident] = {
                "identifier": ident,
                "media_type": m_type,
                "file_count": 0,
                "total_size": 0,
            }
        media_map[ident]["file_count"] += 1
        media_map[ident]["total_size"] += item.file_state.size

    requirements = [ManifestMediaRequirement(**m) for m in media_map.values()]
    requirements.sort(key=lambda x: x.identifier)
    return RestoreManifestSchema(
        total_files=len(cart_items), total_size=total_size, media_required=requirements
    )
