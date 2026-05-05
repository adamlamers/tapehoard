import hashlib
from datetime import datetime, timezone

import pytest
from app.services.scanner import (
    ScannerService,
    JobManager,
    _hash_file_batch_fast,
    _FAST_HASH_BINARY,
)
from app.db import models


def test_job_manager_lifecycle(db_session):
    """Tests the full lifecycle of a job through JobManager."""
    job = JobManager.create_job(db_session, "SCAN")
    assert job.status == "PENDING"

    JobManager.start_job(job.id)
    # Refresh to see changes
    db_session.expire_all()
    job = db_session.get(models.Job, job.id)
    assert job.status == "RUNNING"
    assert job.started_at is not None

    JobManager.update_job(job.id, 50.0, "Processing metadata")
    db_session.expire_all()
    job = db_session.get(models.Job, job.id)
    assert job.progress == 50.0
    assert job.current_task == "Processing metadata"

    JobManager.complete_job(job.id)
    db_session.expire_all()
    job = db_session.get(models.Job, job.id)
    assert job.status == "COMPLETED"
    assert job.progress == 100.0


def test_job_manager_cancellation(db_session):
    """Tests job cancellation logic."""
    job = JobManager.create_job(db_session, "HASH")
    JobManager.cancel_job(job.id)
    assert JobManager.is_cancelled(job.id) is True

    db_session.expire_all()
    job = db_session.get(models.Job, job.id)
    assert job.status == "FAILED"
    assert "Cancelled" in job.error_message


def test_compute_sha256(tmp_path):
    """Tests SHA-256 computation with actual file."""
    scanner = ScannerService()
    test_file = tmp_path / "test.bin"
    content = b"tapehoard test content"
    test_file.write_bytes(content)

    expected_hash = hashlib.sha256(content).hexdigest()
    actual_hash = scanner.compute_sha256(str(test_file))

    assert actual_hash == expected_hash


def test_metadata_sync_batch(db_session):
    """Tests batch metadata synchronization logic."""
    scanner = ScannerService()
    timestamp = datetime.now(timezone.utc)

    batch = [
        {"path": "/data/f1.txt", "size": 100, "mtime": 1000, "ignored": False},
        {"path": "/data/f2.txt", "size": 200, "mtime": 2000, "ignored": True},
    ]

    scanner._sync_metadata_batch(db_session, batch, timestamp)
    db_session.commit()

    # Verify records created
    f1 = (
        db_session.query(models.FilesystemState)
        .filter_by(file_path="/data/f1.txt")
        .first()
    )
    assert f1.size == 100
    assert f1.is_ignored is False

    f2 = (
        db_session.query(models.FilesystemState)
        .filter_by(file_path="/data/f2.txt")
        .first()
    )
    assert f2.is_ignored is True


def test_metadata_update_on_change(db_session):
    """Tests that existing metadata is updated if size/mtime change."""
    scanner = ScannerService()
    timestamp = datetime.now(timezone.utc)

    # Initial state
    f1 = models.FilesystemState(
        file_path="/data/up.txt", size=50, mtime=1, sha256_hash="old"
    )
    db_session.add(f1)
    db_session.commit()

    # Update: size changed
    batch = [{"path": "/data/up.txt", "size": 999, "mtime": 1, "ignored": False}]
    scanner._sync_metadata_batch(db_session, batch, timestamp)
    db_session.commit()

    db_session.refresh(f1)
    assert f1.size == 999
    assert f1.sha256_hash is None  # Should be reset for re-hashing


def test_scan_sources_mocked(db_session, mocker):
    """Tests the discovery scan with mocked filesystem."""
    scanner = ScannerService()

    # Disable fast find so the test uses the os.walk fallback path
    mocker.patch("app.services.scanner._FAST_FIND_BINARY", None)

    # Mock settings
    mocker.patch("app.api.common.get_source_roots", return_value=["/mock_source"])
    mocker.patch("app.api.common.get_exclusion_spec", return_value=None)

    # Mock os.walk and os.stat
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("os.walk", return_value=[("/mock_source", ["subdir"], ["file.txt"])])

    mock_stat = mocker.MagicMock()
    mock_stat.st_size = 500
    mock_stat.st_mtime = 12345
    mocker.patch("os.stat", return_value=mock_stat)

    scanner.scan_sources(db_session)

    # Verify file was discovered
    record = (
        db_session.query(models.FilesystemState)
        .filter_by(file_path="/mock_source/file.txt")
        .first()
    )
    assert record is not None
    assert record.size == 500


def test_hash_file_batch_fast(tmp_path):
    """Tests native sha256sum/shasum batch hashing if available."""
    if _FAST_HASH_BINARY is None:
        pytest.skip("No native hash binary available")

    # Create test files
    files = {}
    for i in range(5):
        content = f"test content {i}".encode()
        f = tmp_path / f"file_{i}.txt"
        f.write_bytes(content)
        files[str(f)] = hashlib.sha256(content).hexdigest()

    # Hash via native binary
    results = _hash_file_batch_fast(list(files.keys()), _FAST_HASH_BINARY)

    assert len(results) == 5
    for path, expected_hash in files.items():
        assert results[path] == expected_hash


def test_hash_file_batch_fast_empty():
    """Tests that empty batch returns empty results."""
    if _FAST_HASH_BINARY is None:
        pytest.skip("No native hash binary available")

    results = _hash_file_batch_fast([], _FAST_HASH_BINARY)
    assert results == {}


def test_hash_file_batch_fast_nonexistent():
    """Tests that non-existent files are gracefully handled."""
    if _FAST_HASH_BINARY is None:
        pytest.skip("No native hash binary available")

    results = _hash_file_batch_fast(["/nonexistent/path"], _FAST_HASH_BINARY)
    # Non-existent files may or may not appear in results depending on binary behavior
    assert isinstance(results, dict)


def test_missing_file_marked_deleted_at_end_of_scan(db_session, mocker):
    """Tests that files not seen during a scan are marked as deleted."""
    scanner = ScannerService()

    mocker.patch("app.services.scanner._FAST_FIND_BINARY", None)
    mocker.patch("app.api.common.get_source_roots", return_value=["/mock_source"])
    mocker.patch("app.api.common.get_exclusion_spec", return_value=None)
    mocker.patch("os.walk", return_value=[])

    # os.path.exists returns True for source roots, False for the missing file
    def mock_exists(path):
        return path != "/old/missing.txt"

    mocker.patch("os.path.exists", side_effect=mock_exists)

    old_timestamp = datetime.now(timezone.utc).replace(year=2020)
    existing_file = models.FilesystemState(
        file_path="/old/missing.txt",
        size=100,
        mtime=1,
        is_ignored=False,
        is_deleted=False,
        last_seen_timestamp=old_timestamp,
    )
    db_session.add(existing_file)
    db_session.commit()

    scanner.scan_sources(db_session)
    db_session.expire_all()

    db_session.refresh(existing_file)
    assert existing_file.is_deleted is True
    assert scanner.files_missing > 0


def test_existing_file_not_marked_deleted(db_session, mocker):
    """Tests that files found during scan retain is_deleted=False."""
    scanner = ScannerService()

    mocker.patch("app.services.scanner._FAST_FIND_BINARY", None)
    mocker.patch("app.api.common.get_source_roots", return_value=["/mock_source"])
    mocker.patch("app.api.common.get_exclusion_spec", return_value=None)
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("os.walk", return_value=[("/mock_source", [], ["file.txt"])])

    mock_stat = mocker.MagicMock()
    mock_stat.st_size = 100
    mock_stat.st_mtime = 99999
    mocker.patch("os.stat", return_value=mock_stat)

    old_timestamp = datetime.now(timezone.utc).replace(year=2020)
    existing_file = models.FilesystemState(
        file_path="/mock_source/file.txt",
        size=50,
        mtime=1,
        is_ignored=False,
        is_deleted=False,
        last_seen_timestamp=old_timestamp,
    )
    db_session.add(existing_file)
    db_session.commit()

    scanner.scan_sources(db_session)
    db_session.expire_all()

    db_session.refresh(existing_file)
    assert existing_file.is_deleted is False
    assert existing_file.size == 100


def test_missing_file_during_hashing_marked_deleted(db_session, mocker):
    """Tests that files missing during hashing are marked as deleted."""
    scanner = ScannerService()

    mocker.patch("app.services.scanner._FAST_HASH_BINARY", None)

    f = models.FilesystemState(
        file_path="/data/vanished.bin", size=10, mtime=1, is_ignored=False
    )
    db_session.add(f)
    db_session.commit()

    mocker.patch.object(ScannerService, "compute_sha256", return_value=None)
    mocker.patch("os.path.exists", return_value=False)

    scanner.run_hashing()
    db_session.refresh(f)
    assert f.is_deleted is True


def test_missing_file_skipped_in_hashing_query(db_session):
    """Tests that already-deleted files are excluded from hashing targets."""
    deleted_file = models.FilesystemState(
        file_path="/data/deleted.bin",
        size=10,
        mtime=1,
        is_ignored=False,
        is_deleted=True,
        sha256_hash=None,
    )
    db_session.add(deleted_file)
    db_session.commit()

    pending = (
        db_session.query(models.FilesystemState)
        .filter(
            models.FilesystemState.sha256_hash.is_(None),
            models.FilesystemState.is_ignored.is_(False),
            models.FilesystemState.is_deleted.is_(False),
        )
        .all()
    )
    assert len(pending) == 0
