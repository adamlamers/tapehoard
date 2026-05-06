from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List, Dict, Any, Literal

from datetime import datetime


class TreeNodeSchema(BaseModel):
    name: str
    path: str
    has_children: bool = True
    children: List["TreeNodeSchema"] = Field(default_factory=list)


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
    is_partially_archived: bool = False
    archived_bytes: int = 0


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


class MediaBaseSchema(BaseModel):
    """Base schema with common fields for all media types."""

    identifier: str
    media_type: str
    capacity: int
    location: Optional[str] = None
    location_building: Optional[str] = None
    location_room: Optional[str] = None
    location_rack: Optional[str] = None
    location_slot: Optional[str] = None


class LtoTapeCreateSchema(MediaBaseSchema):
    """Schema for creating LTO Tape media."""

    media_type: Literal["lto_tape"] = "lto_tape"
    generation: Optional[str] = None  # Auto-detected from hardware if omitted
    capacity: Optional[int] = None  # Auto-detected from hardware MAM if omitted
    worm: bool = False
    write_protected: bool = False
    compression: bool = True
    encryption_key_id: Optional[str] = None
    cleaning_cartridge: bool = False
    # Reference to encryption passphrase in the settings keystore
    encryption_secret_name: Optional[str] = None
    # Device path for hardware auto-detection (e.g. /dev/nst0)
    device_path: Optional[str] = None


class OfflineHddCreateSchema(MediaBaseSchema):
    """Schema for creating Offline HDD media."""

    media_type: Literal["local_hdd"] = "local_hdd"
    drive_model: Optional[str] = None
    device_uuid: Optional[str] = None
    is_ssd: bool = False
    mount_path: Optional[str] = None
    filesystem_type: Optional[str] = None
    connection_interface: Optional[str] = None
    encrypted: bool = False
    encryption_key_id: Optional[str] = None
    # Reference to encryption passphrase in the settings keystore
    encryption_secret_name: Optional[str] = None


class CloudCreateSchema(MediaBaseSchema):
    """Schema for creating S3-Compatible Cloud media."""

    media_type: Literal["s3_compat"] = "s3_compat"
    provider_template: str  # aws, minio, wasabi, backblaze, digitalocean, custom
    endpoint_url: str
    region: str
    bucket_name: str
    access_key_id: str
    # References to secrets in the settings keystore
    secret_access_key_name: Optional[str] = None
    path_style_access: bool = False
    storage_class: Optional[str] = None
    max_part_size_mb: int = 5000
    obfuscate_filenames: bool = False
    # Reference to encryption passphrase in the settings keystore
    encryption_secret_name: Optional[str] = None


# Discriminated union type for creating media
# Uses media_type field to route to the correct type-specific schema
MediaCreateSchema = LtoTapeCreateSchema | OfflineHddCreateSchema | CloudCreateSchema


class MediaUpdateSchema(BaseModel):
    """Schema for updating media - all fields optional."""

    status: Optional[str] = None
    location: Optional[str] = None
    location_building: Optional[str] = None
    location_room: Optional[str] = None
    location_rack: Optional[str] = None
    location_slot: Optional[str] = None
    capacity: Optional[int] = None
    # LTO fields
    generation: Optional[str] = None
    worm: Optional[bool] = None
    write_protected: Optional[bool] = None
    compression: Optional[bool] = None
    encryption_key_id: Optional[str] = None
    cleaning_cartridge: Optional[bool] = None
    # HDD fields
    drive_model: Optional[str] = None
    device_uuid: Optional[str] = None
    is_ssd: Optional[bool] = None
    mount_path: Optional[str] = None
    filesystem_type: Optional[str] = None
    connection_interface: Optional[str] = None
    encrypted: Optional[bool] = None
    # Cloud fields
    provider_template: Optional[str] = None
    endpoint_url: Optional[str] = None
    region: Optional[str] = None
    bucket_name: Optional[str] = None
    access_key_id: Optional[str] = None
    secret_access_key_name: Optional[str] = None
    path_style_access: Optional[bool] = None
    storage_class: Optional[str] = None
    max_part_size_mb: Optional[int] = None
    obfuscate_filenames: Optional[bool] = None
    encryption_secret_name: Optional[str] = None


class MediaSchema(BaseModel):
    id: int
    identifier: str
    media_type: str
    generation_tier: Optional[str] = None
    capacity: int
    bytes_used: int
    status: str
    location: Optional[str] = None
    location_building: Optional[str] = None
    location_room: Optional[str] = None
    location_rack: Optional[str] = None
    location_slot: Optional[str] = None
    last_seen: Optional[datetime] = None
    created_at: datetime
    # LTO fields
    generation: Optional[str] = None
    worm: bool = False
    write_protected: bool = False
    compression: bool = True
    encryption_key_id: Optional[str] = None
    cleaning_cartridge: bool = False
    # HDD fields
    drive_model: Optional[str] = None
    device_uuid: Optional[str] = None
    is_ssd: bool = False
    mount_path: Optional[str] = None
    filesystem_type: Optional[str] = None
    connection_interface: Optional[str] = None
    encrypted: bool = False
    # Cloud fields
    provider_template: Optional[str] = None
    endpoint_url: Optional[str] = None
    region: Optional[str] = None
    bucket_name: Optional[str] = None
    access_key_id: Optional[str] = None
    secret_access_key_name: Optional[str] = None
    path_style_access: bool = False
    storage_class: Optional[str] = None
    max_part_size_mb: int = 5000
    obfuscate_filenames: bool = False
    encryption_secret_name: Optional[str] = None
    # Legacy config fallback
    config: Dict[str, Any] = {}
    # Runtime status
    is_online: bool = False
    is_identified: bool = False
    needs_registration: bool = False
    priority_index: int = 0
    host_free_bytes: Optional[int] = None
    host_total_bytes: Optional[int] = None
    live_info: Optional[Dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)


class StorageProviderSchema(BaseModel):
    provider_id: str
    name: str
    description: str
    capabilities: Dict[str, bool]
    config_schema: Dict[str, Any]
