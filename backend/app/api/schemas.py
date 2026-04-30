from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime


class TreeNodeSchema(BaseModel):
    name: str
    path: str
    has_children: bool = True


class ItemMetadataSchema(BaseModel):
    id: int
    path: str
    type: str = "file"
    size: int
    mtime: datetime
    last_seen_timestamp: Optional[datetime] = None
    sha256_hash: Optional[str] = None
    is_ignored: bool = False
    is_deleted: bool = False
    exists_on_disk: Optional[bool] = None
    child_count: Optional[int] = 0
    selected: bool = False
    versions: List[Dict[str, Any]] = []


class DiscrepancySchema(BaseModel):
    id: int
    path: str
    size: int
    mtime: datetime
    last_seen_timestamp: Optional[datetime] = None
    sha256_hash: Optional[str] = None
    is_deleted: bool
    has_versions: bool = False


class BatchDiscrepancyAction(BaseModel):
    ids: Optional[List[int]] = None
    path_prefix: Optional[str] = None


class MediaSchema(BaseModel):
    id: int
    identifier: str
    media_type: str
    generation_tier: Optional[str] = None
    capacity: int
    bytes_used: int
    status: str
    location: Optional[str] = None
    last_seen: Optional[datetime] = None
    created_at: datetime
    config: Dict[str, Any]
    is_online: bool = False
    is_identified: bool = False
    needs_registration: bool = False
    priority_index: int = 0
    host_free_bytes: Optional[int] = None
    host_total_bytes: Optional[int] = None
    live_info: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class MediaCreateSchema(BaseModel):
    identifier: str
    media_type: str
    generation_tier: Optional[str] = None
    capacity: int
    location: Optional[str] = None
    config: Dict[str, Any] = {}


class MediaUpdateSchema(BaseModel):
    status: Optional[str] = None
    location: Optional[str] = None
    capacity: Optional[int] = None
    config: Optional[Dict[str, Any]] = None


class StorageProviderSchema(BaseModel):
    provider_id: str
    name: str
    description: str
    capabilities: Dict[str, bool]
    config_schema: Dict[str, Any]
