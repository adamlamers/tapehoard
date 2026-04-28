import tarfile
import io
from app.services.archiver import ArchiverService, RangeFile
from app.db import models


def test_range_file(tmp_path):
    """Tests the RangeFile byte-limited reader."""
    test_file = tmp_path / "large.bin"
    content = b"0123456789abcdefghij"  # 20 bytes
    test_file.write_bytes(content)

    # Read middle 10 bytes
    with RangeFile(str(test_file), offset_start=5, length=10) as rf:
        data = rf.read()
        assert data == b"56789abcde"
        assert len(data) == 10
        # Subsequent reads should be empty
        assert rf.read() == b""


def test_get_unbacked_files(db_session):
    """Tests identifying files that need archival."""
    archiver = ArchiverService()

    # File 1: Completely unbacked
    f1 = models.FilesystemState(
        file_path="/data/new.txt", size=100, mtime=1, is_indexed=True
    )
    # File 2: Partially backed (split)
    f2 = models.FilesystemState(
        file_path="/data/split.bin", size=1000, mtime=1, is_indexed=True
    )
    # File 3: Fully backed
    f3 = models.FilesystemState(
        file_path="/data/done.txt", size=50, mtime=1, is_indexed=True
    )
    db_session.add_all([f1, f2, f3])
    db_session.flush()

    # Add media
    m = models.StorageMedia(
        media_type="hdd", identifier="M1", capacity=10000, status="active"
    )
    db_session.add(m)
    db_session.flush()

    # Add partial version for f2
    v2 = models.FileVersion(
        filesystem_state_id=f2.id,
        media_id=m.id,
        file_number="1",
        offset_start=0,
        offset_end=400,
    )
    # Add full version for f3
    v3 = models.FileVersion(
        filesystem_state_id=f3.id,
        media_id=m.id,
        file_number="1",
        offset_start=0,
        offset_end=50,
    )
    db_session.add_all([v2, v3])
    db_session.commit()

    unbacked = list(archiver.get_unbacked_files(db_session))

    # Should find f1 (completely new) and f2 (needs 600 more bytes)
    paths = [item[0].file_path for item in unbacked]
    assert "/data/new.txt" in paths
    assert "/data/split.bin" in paths
    assert "/data/done.txt" not in paths


def test_assemble_backup_batch(db_session):
    """Tests the bin-packing/batching logic."""
    archiver = ArchiverService()

    # Create media with limited capacity (300MB)
    m = models.StorageMedia(
        media_type="hdd",
        identifier="M2",
        capacity=300 * 1024 * 1024,
        status="active",
        bytes_used=0,
    )
    db_session.add(m)

    # Create files that will exceed capacity (200MB each)
    size_200mb = 200 * 1024 * 1024
    f1 = models.FilesystemState(
        file_path="/f1.bin", size=size_200mb, mtime=1, is_indexed=True
    )
    f2 = models.FilesystemState(
        file_path="/f2.bin", size=size_200mb, mtime=1, is_indexed=True
    )
    db_session.add_all([f1, f2])
    db_session.commit()

    batch = archiver.assemble_backup_batch(db_session, m.id)

    # Batch should contain all of f1 and 100MB of f2
    assert len(batch) == 2
    assert batch[0]["file_state"].file_path == "/f1.bin"
    assert batch[0]["offset_end"] == size_200mb

    assert batch[1]["file_state"].file_path == "/f2.bin"
    # f1 uses 200MB, leaving 100MB for f2
    assert batch[1]["offset_end"] == 100 * 1024 * 1024
    assert batch[1]["is_split"] is True


def test_run_backup_mocked(db_session, mocker, tmp_path):
    """Tests the full backup orchestration with mocked hardware."""
    # Setup staging
    staging = tmp_path / "staging"
    staging.mkdir()
    archiver = ArchiverService(staging_directory=str(staging))

    # Setup Data
    media = models.StorageMedia(
        media_type="hdd",
        identifier="DISK_001",
        capacity=10**9,
        status="active",
        bytes_used=0,
    )
    db_session.add(media)

    source_file = tmp_path / "source.txt"
    source_file.write_bytes(b"hello world")

    f1 = models.FilesystemState(
        file_path=str(source_file),
        size=source_file.stat().st_size,
        mtime=1,
        is_indexed=True,
        sha256_hash="hash1",
    )
    db_session.add(f1)
    db_session.commit()

    # Mock Provider
    mock_provider = mocker.MagicMock()
    mock_provider.capabilities = {"supports_random_access": False}
    mock_provider.identify_media.return_value = "DISK_001"
    mock_provider.prepare_for_write.return_value = True
    mock_provider.write_archive.return_value = "ARCH_1"

    mocker.patch.object(archiver, "_get_storage_provider", return_value=mock_provider)

    # Create Job
    from app.services.scanner import JobManager

    job = JobManager.create_job(db_session, "BACKUP")

    archiver.run_backup(db_session, media.id, job.id)

    # Verify result
    db_session.expire_all()
    assert media.bytes_used > 0

    # Verify FileVersion was recorded
    version = (
        db_session.query(models.FileVersion)
        .filter_by(filesystem_state_id=f1.id)
        .first()
    )
    assert version is not None
    assert version.file_number == "ARCH_1"


def test_run_restore_mocked(db_session, mocker, tmp_path):
    """Tests recovery orchestration with mocked hardware."""
    archiver = ArchiverService()
    restore_dest = tmp_path / "restored"

    # Setup Data
    media = models.StorageMedia(
        media_type="hdd", identifier="RESTORE_ME", capacity=10**9, status="active"
    )
    db_session.add(media)
    db_session.flush()

    f1 = models.FilesystemState(file_path="/original/path/data.txt", size=5, mtime=1)
    db_session.add(f1)
    db_session.flush()

    v1 = models.FileVersion(
        filesystem_state_id=f1.id,
        media_id=media.id,
        file_number="1",
        offset_start=0,
        offset_end=5,
    )
    db_session.add(v1)

    # Add to cart
    db_session.add(models.RestoreCart(filesystem_state_id=f1.id))
    db_session.commit()

    # Mock Provider & Tar Stream
    mock_provider = mocker.MagicMock()
    mock_provider.identify_media.return_value = "RESTORE_ME"

    # Create a mock tar stream containing the file
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        content = b"hello"
        tinfo = tarfile.TarInfo(name="original/path/data.txt")
        tinfo.size = len(content)
        tar.addfile(tinfo, io.BytesIO(content))
    buf.seek(0)

    mock_provider.read_archive.return_value = buf
    mocker.patch.object(archiver, "_get_storage_provider", return_value=mock_provider)

    # Run Restore
    from app.services.scanner import JobManager

    job = JobManager.create_job(db_session, "RESTORE")

    archiver.run_restore(db_session, str(restore_dest), job.id)

    # Verify file exists at destination
    expected_file = restore_dest / "original/path/data.txt"
    assert expected_file.exists()
    assert expected_file.read_bytes() == b"hello"
