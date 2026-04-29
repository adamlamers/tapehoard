import tarfile
import io
import pytest
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
    f1 = models.FilesystemState(file_path="/data/new.txt", size=100, mtime=1)
    # File 2: Partially backed (split)
    f2 = models.FilesystemState(file_path="/data/split.bin", size=1000, mtime=1)
    # File 3: Fully backed
    f3 = models.FilesystemState(file_path="/data/done.txt", size=50, mtime=1)
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

    # Create files
    size_200mb = 200 * 1024 * 1024
    f1 = models.FilesystemState(file_path="/f1.bin", size=size_200mb, mtime=1)
    # f2 is 200MB, would fit on fresh tape. Should be skipped on this 300MB tape
    # after f1 (200MB) is added, because only 100MB is left.
    f2 = models.FilesystemState(file_path="/f2.bin", size=size_200mb, mtime=1)
    # f3 is 500MB, larger than total capacity (300MB). SHOULD be split.
    f3 = models.FilesystemState(file_path="/f3.bin", size=500 * 1024 * 1024, mtime=1)
    db_session.add_all([f1, f2, f3])
    db_session.commit()

    batch = archiver.assemble_backup_batch(db_session, m.id)

    # Batch should contain f1 (200MB) and 100MB of f3 (f2 is skipped)
    assert len(batch) == 2
    assert batch[0]["file_state"].file_path == "/f1.bin"
    assert batch[1]["file_state"].file_path == "/f3.bin"
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


def test_archiver_saturated_media_logic(db_session, mocker, tmp_path):
    """Verifies that media is marked full and priority ceded based on hardware feedback."""
    staging = tmp_path / "staging"
    staging.mkdir()
    archiver = ArchiverService(staging_directory=str(staging))

    # Setup Media (HDD for simple mocking)
    media = models.StorageMedia(
        media_type="hdd",
        identifier="FULL_DISK",
        capacity=1000,
        status="active",
        bytes_used=0,
        priority_index=1,
    )
    db_session.add(media)

    # Other media to check priority reordering
    media2 = models.StorageMedia(
        media_type="hdd",
        identifier="NEXT_DISK",
        capacity=1000,
        status="active",
        bytes_used=0,
        priority_index=2,
    )
    db_session.add(media2)

    # Setup a small file to trigger the loop
    source_file = tmp_path / "small.txt"
    source_file.write_bytes(b"data")
    f1 = models.FilesystemState(
        file_path=str(source_file),
        size=4,
        mtime=1,
        sha256_hash="hash_small",
    )
    db_session.add(f1)
    db_session.commit()

    # Mock Provider to report 99% utilization
    mock_provider = mocker.MagicMock()
    mock_provider.capabilities = {"supports_random_access": True}
    mock_provider.identify_media.return_value = "FULL_DISK"
    mock_provider.prepare_for_write.return_value = True
    # Ensure write_file_direct returns a string, not a MagicMock
    mock_provider.write_file_direct.return_value = "LOC_1"
    # FORCE hardware utilization report to 99%
    mock_provider.get_utilization.return_value = 0.99

    mocker.patch.object(archiver, "_get_storage_provider", return_value=mock_provider)

    from app.services.scanner import JobManager

    job = JobManager.create_job(db_session, "BACKUP")

    # Run archival
    archiver.run_backup(db_session, media.id, job.id)

    # EXPECTATION:
    # 1. Media should be marked "full"
    # 2. Priority should be moved to the end (higher than media2)
    db_session.expire_all()
    assert media.status == "full"
    assert media.priority_index > media2.priority_index


def test_archiver_chunking_logic(db_session, mocker, tmp_path):
    """Verifies that large backup batches are split into appropriate chunks."""
    staging = tmp_path / "staging"
    staging.mkdir()
    archiver = ArchiverService(staging_directory=str(staging))

    # Setup Media (Capacity 100GB, target chunk size ~1GB)
    media = models.StorageMedia(
        media_type="tape",
        identifier="TAPE_001",
        capacity=100 * 1024 * 1024 * 1024,
        status="active",
        bytes_used=0,
    )
    db_session.add(media)

    # 1. Add 10 small files (100MB each) -> Should fit in one 1GB chunk
    for i in range(10):
        source_file = tmp_path / f"small_{i}.bin"
        source_file.write_bytes(b"0" * (100 * 1024 * 1024))
        f = models.FilesystemState(
            file_path=str(source_file),
            size=100 * 1024 * 1024,
            mtime=1,
            sha256_hash=f"hash_s_{i}",
        )
        db_session.add(f)

    # 2. Add 1 large file (5GB) -> Exceeds chunk size, should trigger its own chunk
    large_file = tmp_path / "large.bin"
    large_file.write_bytes(b"0" * 10)  # Mock small content for large size metadata
    f_large = models.FilesystemState(
        file_path=str(large_file),
        size=5 * 1024 * 1024 * 1024,
        mtime=1,
        sha256_hash="hash_large",
    )
    # Monkeypatch stat size for test efficiency (don't actually write 5GB to tmp)
    mocker.patch("os.path.getsize", return_value=5 * 1024 * 1024 * 1024)
    # Also patch RangeFile to avoid actual reads
    mocker.patch(
        "app.services.archiver.RangeFile.__enter__", return_value=mocker.MagicMock()
    )
    mocker.patch("app.services.archiver.RangeFile.__exit__")

    db_session.add(f_large)
    db_session.commit()

    # Mock Provider
    mock_provider = mocker.MagicMock()
    mock_provider.capabilities = {"supports_random_access": False}
    mock_provider.identify_media.return_value = "TAPE_001"
    mock_provider.prepare_for_write.return_value = True
    mock_provider.write_archive.return_value = "1"

    mocker.patch.object(archiver, "_get_storage_provider", return_value=mock_provider)

    from app.services.scanner import JobManager

    job = JobManager.create_job(db_session, "BACKUP")

    # Run archival
    archiver.run_backup(db_session, media.id, job.id)

    # EXPECTATION:
    # write_archive should be called TWICE:
    # 1. Once for the 10 small files (combined chunk)
    # 2. Once for the large file (independent chunk)
    assert mock_provider.write_archive.call_count == 2

    # Verify FileVersion was recorded for the large file
    version = (
        db_session.query(models.FileVersion)
        .filter_by(filesystem_state_id=f_large.id)
        .first()
    )
    assert version is not None
    assert version.file_number == "1"


def test_range_file_alignment_guard(tmp_path):
    """Verifies that RangeFile pads truncated files with nulls to maintain tar alignment."""
    from app.services.archiver import RangeFile

    # Create a 50 byte file
    f = tmp_path / "truncated.bin"
    f.write_bytes(b"A" * 50)

    # Initialize RangeFile expecting 100 bytes
    with RangeFile(str(f), offset_start=0, length=100) as rf:
        data = rf.read(100)

        # EXPECTATION:
        # 1. Total length must be exactly 100
        # 2. First 50 are 'A's
        # 3. Last 50 are nulls '\x00'
        assert len(data) == 100
        assert data[:50] == b"A" * 50
        assert data[50:] == b"\x00" * 50


def test_path_traversal_protection():
    """Verifies that the restorer blocks path traversal attempts."""
    archiver = ArchiverService()
    base = "/restores/my_backup"

    # CASE 1: Valid Path
    safe_path = archiver._sanitize_recovery_path(base, "photos/image.jpg")
    assert safe_path.startswith(base)

    # CASE 2: Traversal Attempt (Relative)
    with pytest.raises(PermissionError, match="Restricted path traversal"):
        archiver._sanitize_recovery_path(base, "../../etc/shadow")

    # CASE 3: Traversal Attempt (Absolute-style relative that escapes)
    with pytest.raises(PermissionError, match="Restricted path traversal"):
        archiver._sanitize_recovery_path(base, "/../../etc/shadow")


def test_archiver_restoration_negotiation(db_session, mocker, tmp_path):
    """Verifies that the restorer chooses the correct format (Native vs Tar)."""
    archiver = ArchiverService()

    # Setup Mocks
    mock_media = mocker.MagicMock()
    mock_media.media_type = "cloud"
    mock_media.identifier = "BUCKET1"

    mock_provider = mocker.MagicMock()
    mock_provider.identify_media.return_value = "BUCKET1"
    mock_provider.check_online.return_value = True

    # 1. TEST NATIVE NEGOTIATION
    # Expectation: random_access=True + non-tar ID -> is_tar=False
    mock_provider.capabilities = {"supports_random_access": True}

    # CASE A: Obfuscated object (Native)
    is_tar_native = archiver._test_is_tar_logic(
        mock_provider, mock_media, "objects/a1/b2/hash"
    )
    assert is_tar_native is False

    # CASE B: Obfuscated archive (Tar)
    is_tar_cloud_archive = archiver._test_is_tar_logic(
        mock_provider, mock_media, "archives/a1/b2/hash"
    )
    assert is_tar_cloud_archive is True

    # CASE C: Tape (Always Tar)
    mock_media.media_type = "tape"
    mock_provider.capabilities = {"supports_random_access": False}
    is_tar_tape = archiver._test_is_tar_logic(mock_provider, mock_media, "1")
    assert is_tar_tape is True


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
    mock_provider.check_online.return_value = True
    # FORCE tar path by disabling random access
    mock_provider.capabilities = {"supports_random_access": False}

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
