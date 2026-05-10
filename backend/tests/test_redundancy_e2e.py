"""End-to-end tests for the multiple redundancy feature.

Each test exercises the full backup pipeline — DB setup → run_backup() → DB
assertions — with a mocked storage provider so no real hardware is needed.
"""

from app.db import models
from app.services.archiver import ArchiverService
from app.services.scanner import JobManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider(mocker, identifier: str, archive_id: str = "ARCH_1"):
    """Returns a mock storage provider that impersonates a staging-mode HDD."""
    p = mocker.MagicMock()
    p.capabilities = {"supports_random_access": False}
    p.identify_media.return_value = identifier
    p.prepare_for_write.return_value = True
    p.write_archive.return_value = archive_id
    p.get_utilization.return_value = None
    return p


def _make_media(
    db_session, identifier: str, capacity: int = 10_000_000_000
) -> models.StorageMedia:
    m = models.StorageMedia(
        media_type="hdd",
        identifier=identifier,
        capacity=capacity,
        status="active",
        bytes_used=0,
    )
    db_session.add(m)
    db_session.flush()
    return m


def _make_file(
    db_session, tmp_path, name: str, content: bytes = b"hello world"
) -> models.FilesystemState:
    p = tmp_path / name
    p.write_bytes(content)
    fs = models.FilesystemState(
        file_path=str(p),
        size=len(content),
        mtime=p.stat().st_mtime,
        sha256_hash=f"hash_{name}",
    )
    db_session.add(fs)
    db_session.flush()
    return fs


def _set_redundancy_target(db_session, target: int):
    existing = (
        db_session.query(models.SystemSetting)
        .filter_by(key="redundancy_target")
        .first()
    )
    if existing:
        existing.value = str(target)
    else:
        db_session.add(models.SystemSetting(key="redundancy_target", value=str(target)))
    db_session.flush()


def _run_backup(archiver, db_session, mocker, media, provider):
    """Patch the provider and run a backup job to completion."""
    mocker.patch.object(archiver, "_get_storage_provider", return_value=provider)
    job = JobManager.create_job(db_session, "BACKUP")
    archiver.run_backup(db_session, media.id, job.id)
    db_session.expire_all()
    return db_session.get(models.Job, job.id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_e2e_backup_creates_coverage_row(db_session, mocker, tmp_path):
    """A completed backup at target=1 creates a FileMediaCoverage row and sets
    redundancy_count to 1."""
    staging = tmp_path / "staging"
    staging.mkdir()
    archiver = ArchiverService(staging_directory=str(staging))

    _set_redundancy_target(db_session, 1)
    media = _make_media(db_session, "TAPE_COV1")
    f = _make_file(db_session, tmp_path, "file.txt")
    db_session.commit()

    provider = _make_provider(mocker, "TAPE_COV1")
    job = _run_backup(archiver, db_session, mocker, media, provider)

    assert job.status == "COMPLETED"

    db_session.refresh(f)
    assert f.redundancy_count == 1

    cov = (
        db_session.query(models.FileMediaCoverage)
        .filter_by(file_id=f.id, media_id=media.id)
        .first()
    )
    assert cov is not None, "FileMediaCoverage row must exist after backup"


def test_e2e_target1_second_media_skips_backed_up_file(db_session, mocker, tmp_path):
    """With target=1, a file backed up to media A is not written to media B."""
    staging = tmp_path / "staging"
    staging.mkdir()
    archiver = ArchiverService(staging_directory=str(staging))

    _set_redundancy_target(db_session, 1)
    media_a = _make_media(db_session, "TAPE_A1")
    media_b = _make_media(db_session, "TAPE_B1")
    f = _make_file(db_session, tmp_path, "once.txt")
    db_session.commit()

    # Backup to A
    _run_backup(
        archiver, db_session, mocker, media_a, _make_provider(mocker, "TAPE_A1", "A1")
    )

    db_session.refresh(f)
    assert f.redundancy_count == 1

    # Backup to B — file already at target, should not be written
    _run_backup(
        archiver, db_session, mocker, media_b, _make_provider(mocker, "TAPE_B1", "B1")
    )

    versions_on_b = (
        db_session.query(models.FileVersion).filter_by(media_id=media_b.id).all()
    )
    assert len(versions_on_b) == 0, "No file should be written to media B at target=1"

    db_session.refresh(f)
    assert f.redundancy_count == 1


def test_e2e_target2_both_media_receive_file(db_session, mocker, tmp_path):
    """With target=2, the file is backed up to media A and then to media B,
    resulting in redundancy_count=2."""
    staging = tmp_path / "staging"
    staging.mkdir()
    archiver = ArchiverService(staging_directory=str(staging))

    _set_redundancy_target(db_session, 2)
    media_a = _make_media(db_session, "TAPE_A2")
    media_b = _make_media(db_session, "TAPE_B2")
    f = _make_file(db_session, tmp_path, "redundant.txt")
    db_session.commit()

    # Backup to A (first copy)
    _run_backup(
        archiver, db_session, mocker, media_a, _make_provider(mocker, "TAPE_A2", "A2")
    )

    db_session.refresh(f)
    assert f.redundancy_count == 1

    # Backup to B (second copy)
    _run_backup(
        archiver, db_session, mocker, media_b, _make_provider(mocker, "TAPE_B2", "B2")
    )

    db_session.refresh(f)
    assert f.redundancy_count == 2

    # Both coverage rows must exist
    cov_a = (
        db_session.query(models.FileMediaCoverage)
        .filter_by(file_id=f.id, media_id=media_a.id)
        .first()
    )
    cov_b = (
        db_session.query(models.FileMediaCoverage)
        .filter_by(file_id=f.id, media_id=media_b.id)
        .first()
    )
    assert cov_a is not None
    assert cov_b is not None

    # Both media have FileVersion records for the file
    assert (
        db_session.query(models.FileVersion)
        .filter_by(media_id=media_a.id, filesystem_state_id=f.id)
        .count()
        == 1
    )
    assert (
        db_session.query(models.FileVersion)
        .filter_by(media_id=media_b.id, filesystem_state_id=f.id)
        .count()
        == 1
    )


def test_e2e_target2_satisfied_skips_third_media(db_session, mocker, tmp_path):
    """With target=2, once two copies exist, a third media skips the file."""
    staging = tmp_path / "staging"
    staging.mkdir()
    archiver = ArchiverService(staging_directory=str(staging))

    _set_redundancy_target(db_session, 2)
    media_a = _make_media(db_session, "TAPE_A3")
    media_b = _make_media(db_session, "TAPE_B3")
    media_c = _make_media(db_session, "TAPE_C3")
    f = _make_file(db_session, tmp_path, "twocopy.txt")
    db_session.commit()

    _run_backup(
        archiver, db_session, mocker, media_a, _make_provider(mocker, "TAPE_A3", "A3")
    )
    _run_backup(
        archiver, db_session, mocker, media_b, _make_provider(mocker, "TAPE_B3", "B3")
    )

    db_session.refresh(f)
    assert f.redundancy_count == 2

    _run_backup(
        archiver, db_session, mocker, media_c, _make_provider(mocker, "TAPE_C3", "C3")
    )

    # No versions on C
    assert (
        db_session.query(models.FileVersion).filter_by(media_id=media_c.id).count() == 0
    )
    # Coverage count unchanged
    db_session.refresh(f)
    assert f.redundancy_count == 2


def test_e2e_failed_media_decrements_redundancy(db_session, mocker, tmp_path, client):
    """Marking media as FAILED purges its coverage rows and decrements redundancy_count."""
    staging = tmp_path / "staging"
    staging.mkdir()
    archiver = ArchiverService(staging_directory=str(staging))

    _set_redundancy_target(db_session, 2)
    media_a = _make_media(db_session, "TAPE_F_A")
    media_b = _make_media(db_session, "TAPE_F_B")
    f = _make_file(db_session, tmp_path, "fragile.txt")
    db_session.commit()

    _run_backup(
        archiver, db_session, mocker, media_a, _make_provider(mocker, "TAPE_F_A", "FA")
    )
    _run_backup(
        archiver, db_session, mocker, media_b, _make_provider(mocker, "TAPE_F_B", "FB")
    )

    db_session.refresh(f)
    assert f.redundancy_count == 2

    # Mark media A as FAILED via the API — should purge its coverage
    resp = client.patch(f"/inventory/media/{media_a.id}", json={"status": "FAILED"})
    assert resp.status_code == 200

    db_session.expire_all()
    db_session.refresh(f)
    assert f.redundancy_count == 1, "redundancy_count must drop when media fails"

    cov_a = (
        db_session.query(models.FileMediaCoverage)
        .filter_by(file_id=f.id, media_id=media_a.id)
        .first()
    )
    assert cov_a is None, "Coverage row for failed media must be removed"


def test_e2e_initialize_media_resets_coverage(db_session, mocker, tmp_path, client):
    """Re-initializing a media wipes its file_versions and coverage rows,
    causing the file to become a backup candidate again."""
    staging = tmp_path / "staging"
    staging.mkdir()
    archiver = ArchiverService(staging_directory=str(staging))

    _set_redundancy_target(db_session, 1)
    media = _make_media(db_session, "TAPE_INIT")
    f = _make_file(db_session, tmp_path, "wipe_me.txt")
    db_session.commit()

    _run_backup(
        archiver, db_session, mocker, media, _make_provider(mocker, "TAPE_INIT", "I1")
    )

    db_session.refresh(f)
    assert f.redundancy_count == 1

    # Patch provider so initialize_media succeeds
    mock_init_provider = mocker.MagicMock()
    mock_init_provider.check_existing_data.return_value = False
    mock_init_provider.initialize_media.return_value = True
    mock_init_provider.device_path = "/dev/nst0"

    mocker.patch(
        "app.services.archiver.archiver_manager._get_storage_provider",
        return_value=mock_init_provider,
    )

    resp = client.post(f"/inventory/media/{media.id}/initialize")
    assert resp.status_code == 200

    db_session.expire_all()
    db_session.refresh(f)
    assert f.redundancy_count == 0, "redundancy_count must be 0 after tape wipe"

    assert (
        db_session.query(models.FileVersion).filter_by(media_id=media.id).count() == 0
    )
    assert (
        db_session.query(models.FileMediaCoverage).filter_by(media_id=media.id).count()
        == 0
    )


def test_e2e_multiple_files_mixed_redundancy(db_session, mocker, tmp_path):
    """Verifies batch selection correctly mixes first-time and redundant files."""
    staging = tmp_path / "staging"
    staging.mkdir()
    archiver = ArchiverService(staging_directory=str(staging))

    _set_redundancy_target(db_session, 2)
    media_a = _make_media(db_session, "TAPE_MIX_A")
    media_b = _make_media(db_session, "TAPE_MIX_B")

    # f1: already backed up to A (needs one more copy)
    f1 = _make_file(db_session, tmp_path, "existing.txt", b"existing data")
    # f2: brand-new file (needs first backup)
    f2 = _make_file(db_session, tmp_path, "new.txt", b"new data")
    db_session.commit()

    # Back up f1 to media A first
    _run_backup(
        archiver,
        db_session,
        mocker,
        media_a,
        _make_provider(mocker, "TAPE_MIX_A", "MA"),
    )

    db_session.refresh(f1)
    db_session.refresh(f2)
    assert f1.redundancy_count == 1
    assert f2.redundancy_count == 1  # f2 was also backed up in same run

    # Run backup for media B: both f1 and f2 should need a second copy
    _run_backup(
        archiver,
        db_session,
        mocker,
        media_b,
        _make_provider(mocker, "TAPE_MIX_B", "MB"),
    )

    db_session.refresh(f1)
    db_session.refresh(f2)
    assert f1.redundancy_count == 2
    assert f2.redundancy_count == 2

    assert (
        db_session.query(models.FileVersion)
        .filter_by(media_id=media_b.id, filesystem_state_id=f1.id)
        .count()
        == 1
    )
    assert (
        db_session.query(models.FileVersion)
        .filter_by(media_id=media_b.id, filesystem_state_id=f2.id)
        .count()
        == 1
    )


def test_e2e_redundancy_target_setting_controls_backup(db_session, mocker, tmp_path):
    """Changing redundancy_target from 1 to 2 causes previously-satisfied files
    to appear as candidates again."""
    staging = tmp_path / "staging"
    staging.mkdir()
    archiver = ArchiverService(staging_directory=str(staging))

    _set_redundancy_target(db_session, 1)
    media_a = _make_media(db_session, "TAPE_SET_A")
    media_b = _make_media(db_session, "TAPE_SET_B")
    f = _make_file(db_session, tmp_path, "setting_test.txt")
    db_session.commit()

    # Backup at target=1 → satisfied on A
    _run_backup(
        archiver,
        db_session,
        mocker,
        media_a,
        _make_provider(mocker, "TAPE_SET_A", "SA"),
    )

    db_session.refresh(f)
    assert f.redundancy_count == 1

    # Raise target to 2
    _set_redundancy_target(db_session, 2)
    db_session.commit()

    # Backup to B → file should now be a candidate (needs 2nd copy)
    _run_backup(
        archiver,
        db_session,
        mocker,
        media_b,
        _make_provider(mocker, "TAPE_SET_B", "SB"),
    )

    db_session.refresh(f)
    assert f.redundancy_count == 2
    assert (
        db_session.query(models.FileVersion)
        .filter_by(media_id=media_b.id, filesystem_state_id=f.id)
        .count()
        == 1
    )
