from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import Integer, String, Float, ForeignKey, DateTime, Boolean, BigInteger
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class FilesystemState(Base):
    __tablename__ = "filesystem_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_path: Mapped[str] = mapped_column(String, index=True, unique=True)
    size: Mapped[int] = mapped_column(BigInteger)
    mtime: Mapped[float] = mapped_column(Float)
    sha256_hash: Mapped[Optional[str]] = mapped_column(
        String, index=True, nullable=True
    )
    is_indexed: Mapped[bool] = mapped_column(Boolean, default=False)  # True if hashed
    is_ignored: Mapped[bool] = mapped_column(
        Boolean, default=False
    )  # True if matches exclusion
    last_seen_timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    versions: Mapped[List["FileVersion"]] = relationship(back_populates="file_state")


class StorageMedia(Base):
    __tablename__ = "storage_media"

    id: Mapped[int] = mapped_column(primary_key=True)
    media_type: Mapped[str] = mapped_column(String)  # tape, hdd, cloud
    identifier: Mapped[str] = mapped_column(
        String, unique=True, index=True
    )  # barcode, UUID, bucket
    generation_tier: Mapped[Optional[str]] = mapped_column(
        String
    )  # e.g., LTO-6, S3 Standard
    capacity: Mapped[int] = mapped_column(BigInteger)  # Native capacity in bytes
    bytes_used: Mapped[int] = mapped_column(BigInteger, default=0)
    location: Mapped[Optional[str]] = mapped_column(String)
    status: Mapped[str] = mapped_column(
        String, default="active"
    )  # active, full, retired, offline
    extra_config: Mapped[Optional[str]] = mapped_column(
        String
    )  # JSON config for type-specific details

    versions: Mapped[List["FileVersion"]] = relationship(back_populates="media")


class BackupJob(Base):
    __tablename__ = "backups"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_name: Mapped[str] = mapped_column(String)
    job_type: Mapped[str] = mapped_column(String)  # initial, incremental
    start_time: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String)  # running, success, failed, aborted

    logs: Mapped[List["JobLog"]] = relationship(back_populates="backup")


class FileVersion(Base):
    __tablename__ = "file_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    filesystem_state_id: Mapped[int] = mapped_column(ForeignKey("filesystem_state.id"))
    media_id: Mapped[int] = mapped_column(ForeignKey("storage_media.id"))
    file_number: Mapped[str] = mapped_column(String)  # Tape position or object path
    offset_in_tar: Mapped[Optional[int]] = mapped_column(Integer)

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
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class JobLog(Base):
    __tablename__ = "job_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    backup_id: Mapped[int] = mapped_column(ForeignKey("backups.id"))
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    log_level: Mapped[str] = mapped_column(String)  # INFO, ERROR, WARN
    message: Mapped[str] = mapped_column(String)

    backup: Mapped["BackupJob"] = relationship(back_populates="logs")
