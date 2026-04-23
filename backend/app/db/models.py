from datetime import datetime
from typing import Optional, List

from sqlalchemy import Integer, String, Float, ForeignKey, DateTime, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class FilesystemState(Base):
    __tablename__ = "filesystem_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_path: Mapped[str] = mapped_column(String, index=True, unique=True)
    size: Mapped[int] = mapped_column(Integer)
    mtime: Mapped[float] = mapped_column(Float)
    sha256_hash: Mapped[Optional[str]] = mapped_column(String, index=True)
    last_seen_timestamp: Mapped[datetime] = mapped_column(DateTime)

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
    capacity: Mapped[int] = mapped_column(Integer)  # Native capacity in bytes
    bytes_used: Mapped[int] = mapped_column(Integer, default=0)
    location: Mapped[Optional[str]] = mapped_column(String)
    status: Mapped[str] = mapped_column(
        String, default="active"
    )  # active, full, retired, offline

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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class JobLog(Base):
    __tablename__ = "job_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    backup_id: Mapped[int] = mapped_column(ForeignKey("backups.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    log_level: Mapped[str] = mapped_column(String)  # INFO, WARN, ERROR
    message: Mapped[str] = mapped_column(String)

    backup: Mapped["BackupJob"] = relationship(back_populates="logs")
