from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import Integer, String, Float, ForeignKey, DateTime, Boolean, BigInteger
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class FilesystemState(Base):
    __tablename__ = "filesystem_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_path: Mapped[str] = mapped_column(String, unique=True)
    size: Mapped[int] = mapped_column(BigInteger)
    mtime: Mapped[float] = mapped_column(Float)
    sha256_hash: Mapped[Optional[str]] = mapped_column(
        String, index=True, nullable=True
    )
    is_ignored: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # Effective ignored state (manual OR policy, with manual override)
    is_ignored_by_policy: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # True if excluded by global policy (excludes manual tracking rules)
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # True if confirmed missing from disk
    missing_acknowledged_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True, index=True
    )  # User acknowledged this missing file; hide from discrepancies
    last_seen_timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )

    redundancy_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )

    versions: Mapped[List["FileVersion"]] = relationship(back_populates="file_state")


class StorageMedia(Base):
    __tablename__ = "storage_media"

    id: Mapped[int] = mapped_column(primary_key=True)
    media_type: Mapped[str] = mapped_column(String)  # lto_tape, local_hdd, s3_compat
    identifier: Mapped[str] = mapped_column(
        String, unique=True, index=True
    )  # barcode, UUID, bucket
    generation_tier: Mapped[Optional[str]] = mapped_column(
        String
    )  # e.g., LTO-6, S3 Standard (kept for backward compat)
    capacity: Mapped[int] = mapped_column(BigInteger)  # Native capacity in bytes
    bytes_used: Mapped[int] = mapped_column(BigInteger, default=0)
    # Structured location fields
    location: Mapped[Optional[str]] = mapped_column(String)  # Kept as display fallback
    location_building: Mapped[Optional[str]] = mapped_column(String)
    location_room: Mapped[Optional[str]] = mapped_column(String)
    location_rack: Mapped[Optional[str]] = mapped_column(String)
    location_slot: Mapped[Optional[str]] = mapped_column(String)
    status: Mapped[str] = mapped_column(
        String, default="active"
    )  # active, full, retired, offline
    extra_config: Mapped[Optional[str]] = mapped_column(
        String
    )  # JSON config for type-specific details
    priority_index: Mapped[int] = mapped_column(Integer, default=0)
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    # Type-specific fields for LTO Tape
    generation: Mapped[Optional[str]] = mapped_column(String)  # LTO-6, LTO-7, etc.
    worm: Mapped[bool] = mapped_column(Boolean, default=False)
    write_protected: Mapped[bool] = mapped_column(Boolean, default=False)
    compression: Mapped[bool] = mapped_column(Boolean, default=True)
    encryption_key_id: Mapped[Optional[str]] = mapped_column(String)
    cleaning_cartridge: Mapped[bool] = mapped_column(Boolean, default=False)

    # Type-specific fields for Offline HDD
    drive_model: Mapped[Optional[str]] = mapped_column(String)
    device_uuid: Mapped[Optional[str]] = mapped_column(String)
    is_ssd: Mapped[bool] = mapped_column(Boolean, default=False)
    mount_path: Mapped[Optional[str]] = mapped_column(String)
    filesystem_type: Mapped[Optional[str]] = mapped_column(String)
    connection_interface: Mapped[Optional[str]] = mapped_column(String)
    encrypted: Mapped[bool] = mapped_column(Boolean, default=False)

    # Type-specific fields for S3-Compatible Cloud
    provider_template: Mapped[Optional[str]] = mapped_column(
        String
    )  # aws, minio, wasabi, etc.
    endpoint_url: Mapped[Optional[str]] = mapped_column(String)
    region: Mapped[Optional[str]] = mapped_column(String)
    bucket_name: Mapped[Optional[str]] = mapped_column(String)
    access_key_id: Mapped[Optional[str]] = mapped_column(String)
    # DEPRECATED: raw secret values are no longer stored on media records.
    # Use secret_access_key_name (reference to settings keystore) instead.
    secret_access_key: Mapped[Optional[str]] = mapped_column(String)
    secret_access_key_name: Mapped[Optional[str]] = mapped_column(
        String
    )  # Reference to settings secrets keystore
    path_style_access: Mapped[bool] = mapped_column(Boolean, default=False)
    storage_class: Mapped[Optional[str]] = mapped_column(String)
    max_part_size_mb: Mapped[int] = mapped_column(Integer, default=5000)
    obfuscate_filenames: Mapped[bool] = mapped_column(Boolean, default=False)
    # DEPRECATED: raw passphrase values are no longer stored on media records.
    # Use encryption_secret_name (reference to settings keystore) instead.
    client_side_encryption_passphrase: Mapped[Optional[str]] = mapped_column(String)
    encryption_secret_name: Mapped[Optional[str]] = mapped_column(
        String
    )  # Reference to settings secrets keystore

    versions: Mapped[List["FileVersion"]] = relationship(back_populates="media")


class FileVersion(Base):
    __tablename__ = "file_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    filesystem_state_id: Mapped[int] = mapped_column(ForeignKey("filesystem_state.id"))
    media_id: Mapped[int] = mapped_column(ForeignKey("storage_media.id"))
    file_number: Mapped[str] = mapped_column(String)  # Tape position or object path
    offset_in_tar: Mapped[Optional[int]] = mapped_column(Integer)

    # Split File Support
    is_split: Mapped[bool] = mapped_column(Boolean, default=False)
    split_id: Mapped[Optional[str]] = mapped_column(
        String, nullable=True
    )  # UUID grouping parts
    offset_start: Mapped[int] = mapped_column(BigInteger, default=0)
    offset_end: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    file_state: Mapped["FilesystemState"] = relationship(back_populates="versions")
    media: Mapped["StorageMedia"] = relationship(back_populates="versions")


class TrackedSource(Base):
    __tablename__ = "tracked_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String, unique=True, index=True)
    is_directory: Mapped[bool] = mapped_column(Boolean, default=True)
    action: Mapped[str] = mapped_column(String, default="include")  # include, exclude
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class RestoreCart(Base):
    __tablename__ = "restore_cart"

    id: Mapped[int] = mapped_column(primary_key=True)
    filesystem_state_id: Mapped[int] = mapped_column(ForeignKey("filesystem_state.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    file_state: Mapped["FilesystemState"] = relationship()


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_type: Mapped[str] = mapped_column(String)  # SCAN, BACKUP, RESTORE
    status: Mapped[str] = mapped_column(
        String, default="PENDING"
    )  # PENDING, RUNNING, COMPLETED, FAILED
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    current_task: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    logs: Mapped[List["JobLog"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class JobLog(Base):
    __tablename__ = "job_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"))
    message: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    job: Mapped["Job"] = relationship(back_populates="logs")


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class FileMediaCoverage(Base):
    __tablename__ = "file_media_coverage"

    file_id: Mapped[int] = mapped_column(
        ForeignKey("filesystem_state.id", ondelete="CASCADE"), primary_key=True
    )
    media_id: Mapped[int] = mapped_column(
        ForeignKey("storage_media.id", ondelete="CASCADE"), primary_key=True
    )
