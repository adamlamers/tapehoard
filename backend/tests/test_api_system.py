import json
from datetime import datetime, timezone

import pytest

from app.db import models


def test_get_dashboard_stats_empty(client):
    """Tests the dashboard stats endpoint when the database is empty."""
    response = client.get("/system/dashboard/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_data_size"] == 0
    assert data["unprotected_files_count"] == 0
    assert data["media_distribution"] == {"LTO": 0, "HDD": 0, "Cloud": 0}


def test_get_dashboard_stats_populated(client, db_session):
    """Tests the dashboard stats endpoint with actual data."""
    # Add a file
    file_state = models.FilesystemState(
        file_path="/source_data/file1.txt",
        size=1024,
        mtime=datetime.now(timezone.utc).timestamp(),
        is_ignored=False,
    )
    db_session.add(file_state)
    db_session.commit()

    response = client.get("/system/dashboard/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["unprotected_files_count"] == 1
    assert data["unprotected_data_size"] == 1024


def test_get_dashboard_stats_redundancy_ratio(client, db_session):
    """Verifies the redundancy ratio is coherent and based on data volume.

    The ratio is computed as (archived_bytes / eligible_bytes) * 100.
    It should be 0 when no versions exist, positive when versions exist,
    and should not produce nonsensical negative or division-by-zero values.
    """
    # Create 3 eligible files with different sizes
    file_sizes = [100, 200, 300]
    for i, size in enumerate(file_sizes):
        f = models.FilesystemState(
            file_path=f"/source_data/file{i}.txt",
            size=size,
            mtime=datetime.now(timezone.utc).timestamp(),
            is_ignored=False,
        )
        db_session.add(f)

    # Create 1 ignored file (should not count toward denominator)
    ignored = models.FilesystemState(
        file_path="/source_data/ignored.txt",
        size=50,
        mtime=datetime.now(timezone.utc).timestamp(),
        is_ignored=True,
    )
    db_session.add(ignored)
    db_session.commit()

    # No versions yet → ratio should be 0
    response = client.get("/system/dashboard/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["redundancy_ratio"] == 0.0

    # Create an active tape and archive versions
    tape = models.StorageMedia(
        media_type="tape",
        identifier="TAPE_REDUNDANCY",
        capacity=10_000_000_000,
        status="active",
        bytes_used=0,
    )
    db_session.add(tape)
    db_session.commit()

    # Add 5 versions across the 3 files, each covering 100 bytes
    files = (
        db_session.query(models.FilesystemState)
        .filter(models.FilesystemState.is_ignored == False)  # noqa: E712
        .all()
    )
    for i in range(5):
        db_session.add(
            models.FileVersion(
                filesystem_state_id=files[i % 3].id,
                media_id=tape.id,
                file_number=str(i),
                offset_start=0,
                offset_end=100,
            )
        )
    db_session.commit()

    response = client.get("/system/dashboard/stats")
    assert response.status_code == 200
    data = response.json()
    # archived_size = 5 * 100 = 500
    # eligible_size = 100 + 200 + 300 = 600
    # ratio = 500 / 600 * 100 = 83.3
    assert data["redundancy_ratio"] == pytest.approx(83.3, abs=0.1)
    assert data["redundancy_ratio"] >= 0

    # Mark tape as full (still counts toward versions)
    tape.status = "full"
    db_session.commit()

    response = client.get("/system/dashboard/stats")
    assert response.status_code == 200
    data = response.json()
    # Full media still counts, so ratio should stay the same
    assert data["redundancy_ratio"] == pytest.approx(83.3, abs=0.1)

    # Retire the tape (versions should no longer count)
    tape.status = "retired"
    db_session.commit()

    response = client.get("/system/dashboard/stats")
    assert response.status_code == 200
    data = response.json()
    # No active/full media → no counted versions → ratio 0
    assert data["redundancy_ratio"] == 0.0


def test_trigger_scan(client):
    """Tests triggering a system scan."""
    response = client.post("/system/scan")
    assert response.status_code == 200
    assert "job_id" in response.json()
    assert response.json()["message"] == "Scan started"


def test_get_scan_status(client):
    """Tests retrieving the scanner status."""
    response = client.get("/system/scan/status")
    assert response.status_code == 200
    data = response.json()
    assert "is_running" in data
    assert "files_processed" in data


def test_ls_root(client):
    """Tests listing the root directory returns actual subdirectories."""
    response = client.get("/system/ls?path=/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    for entry in data:
        assert "name" in entry
        assert "path" in entry
        assert entry["name"] != ""
        assert entry["path"] != ""


def test_ignore_hardware(client):
    """Tests adding a hardware identifier to the ignore list."""
    response = client.post("/system/hardware/ignore", json={"identifier": "DISK_001"})
    assert response.status_code == 200
    assert response.json() == {"message": "Hardware node ignored."}

    # Verify in settings
    response = client.get("/system/settings")
    assert "ignored_hardware" in response.json()
    assert "DISK_001" in response.json()["ignored_hardware"]


def test_scan_status_includes_files_missing(client):
    """Tests that scan status includes the files_missing metric."""
    response = client.get("/system/scan/status")
    assert response.status_code == 200
    data = response.json()
    assert "files_missing" in data
    assert data["files_missing"] == 0


def test_dashboard_stats_excludes_failed_media(client, db_session):
    """Tests that dashboard stats do not count versions on failed or retired media."""
    active_media = models.StorageMedia(
        media_type="hdd", identifier="M1", capacity=5000, status="active"
    )
    failed_media = models.StorageMedia(
        media_type="tape", identifier="TAPE_01", capacity=5000, status="failed"
    )
    retired_media = models.StorageMedia(
        media_type="tape", identifier="TAPE_02", capacity=5000, status="retired"
    )
    db_session.add_all([active_media, failed_media, retired_media])
    db_session.flush()

    file1 = models.FilesystemState(
        file_path="/source/only_active.txt",
        size=2048,
        mtime=1000,
        is_ignored=False,
    )
    file2 = models.FilesystemState(
        file_path="/source/only_failed.txt",
        size=4096,
        mtime=1000,
        is_ignored=False,
    )
    file3 = models.FilesystemState(
        file_path="/source/only_retired.txt",
        size=8192,
        mtime=1000,
        is_ignored=False,
    )
    db_session.add_all([file1, file2, file3])
    db_session.flush()

    db_session.add(
        models.FileVersion(
            filesystem_state_id=file1.id,
            media_id=active_media.id,
            file_number="1",
            offset_start=0,
            offset_end=2048,
        )
    )
    db_session.add(models.FileMediaCoverage(file_id=file1.id, media_id=active_media.id))
    db_session.add(
        models.FileVersion(
            filesystem_state_id=file2.id,
            media_id=failed_media.id,
            file_number="1",
            offset_start=0,
            offset_end=4096,
        )
    )
    db_session.add(
        models.FileVersion(
            filesystem_state_id=file3.id,
            media_id=retired_media.id,
            file_number="1",
            offset_start=0,
            offset_end=8192,
        )
    )
    db_session.commit()

    response = client.get("/system/dashboard/stats")
    assert response.status_code == 200
    data = response.json()

    assert data["unprotected_files_count"] == 2
    assert data["unprotected_data_size"] == 12288
    assert data["archived_data_size"] == 2048


def test_dashboard_stats_counts_only_archived_bytes(client, db_session):
    """Tests that archived_data_size counts only written bytes, not full file size."""
    active_media = models.StorageMedia(
        media_type="hdd", identifier="M1", capacity=5000, status="active"
    )
    db_session.add(active_media)
    db_session.flush()

    # File 1: fully archived (2048 bytes)
    file1 = models.FilesystemState(
        file_path="/source/full.txt", size=2048, mtime=1000, is_ignored=False
    )
    # File 2: partially archived (only 500 of 3000 bytes)
    file2 = models.FilesystemState(
        file_path="/source/partial.bin", size=3000, mtime=1000, is_ignored=False
    )
    db_session.add_all([file1, file2])
    db_session.flush()

    db_session.add(
        models.FileVersion(
            filesystem_state_id=file1.id,
            media_id=active_media.id,
            file_number="1",
            offset_start=0,
            offset_end=2048,
        )
    )
    db_session.add(models.FileMediaCoverage(file_id=file1.id, media_id=active_media.id))
    db_session.add(
        models.FileVersion(
            filesystem_state_id=file2.id,
            media_id=active_media.id,
            file_number="1",
            offset_start=0,
            offset_end=500,
        )
    )
    db_session.commit()

    response = client.get("/system/dashboard/stats")
    assert response.status_code == 200
    data = response.json()

    # Archived data = 2048 + 500 = 2548, NOT 2048 + 3000
    assert data["archived_data_size"] == 2548
    # Unprotected count = 1 (partial file has no complete copy, redundancy_count=0)
    assert data["unprotected_files_count"] == 1
    # Unprotected size = 3000 (full size of file2 — no complete copy exists)
    assert data["unprotected_data_size"] == 3000


def test_discrepancies_excludes_versions_on_unavailable_media(client, db_session):
    """Tests that discrepancy has_versions is False when only backed up on failed/retired media."""
    failed_media = models.StorageMedia(
        media_type="tape", identifier="TAPE_BAD", capacity=5000, status="failed"
    )
    retired_media = models.StorageMedia(
        media_type="tape", identifier="TAPE_OLD", capacity=5000, status="retired"
    )
    active_media = models.StorageMedia(
        media_type="hdd", identifier="M_OK", capacity=5000, status="active"
    )
    db_session.add_all([failed_media, retired_media, active_media])
    db_session.flush()

    file_failed = models.FilesystemState(
        file_path="/data/gone_failed.txt",
        size=500,
        mtime=1000,
        is_deleted=True,
        is_ignored=False,
    )
    file_retired = models.FilesystemState(
        file_path="/data/gone_retired.txt",
        size=600,
        mtime=1000,
        is_deleted=True,
        is_ignored=False,
    )
    file_good = models.FilesystemState(
        file_path="/data/exists_on_good.txt",
        size=700,
        mtime=1000,
        is_deleted=True,
        is_ignored=False,
    )
    db_session.add_all([file_failed, file_retired, file_good])
    db_session.flush()

    db_session.add(
        models.FileVersion(
            filesystem_state_id=file_failed.id,
            media_id=failed_media.id,
            file_number="1",
            offset_start=0,
            offset_end=500,
        )
    )
    db_session.add(
        models.FileVersion(
            filesystem_state_id=file_retired.id,
            media_id=retired_media.id,
            file_number="1",
            offset_start=0,
            offset_end=600,
        )
    )
    db_session.add(
        models.FileVersion(
            filesystem_state_id=file_good.id,
            media_id=active_media.id,
            file_number="1",
            offset_start=0,
            offset_end=700,
        )
    )
    db_session.commit()

    response = client.get("/system/discrepancies")
    assert response.status_code == 200
    data = response.json()

    assert len(data) == 3

    failed_backed = next(d for d in data if d["path"] == "/data/gone_failed.txt")
    assert failed_backed["has_versions"] is False

    retired_backed = next(d for d in data if d["path"] == "/data/gone_retired.txt")
    assert retired_backed["has_versions"] is False

    good_backed = next(d for d in data if d["path"] == "/data/exists_on_good.txt")
    assert good_backed["has_versions"] is True


# ── Secrets Keystore ──


def test_list_secrets_empty(client):
    """Tests listing secrets when keystore is empty."""
    response = client.get("/system/secrets")
    assert response.status_code == 200
    assert response.json() == []


def test_create_and_list_secret(client):
    """Tests creating a secret and verifying it appears in the list."""
    response = client.post(
        "/system/secrets", json={"name": "my-api-key", "value": "secret123"}
    )
    assert response.status_code == 200
    assert "stored" in response.json()["message"]

    response = client.get("/system/secrets")
    assert response.status_code == 200
    assert "my-api-key" in response.json()


def test_get_secret_value(client):
    """Tests that secret values are not retrievable by name endpoint; name still appears in list."""
    client.post(
        "/system/secrets", json={"name": "encryption-key", "value": "super-secret"}
    )

    response = client.get("/system/secrets/encryption-key")
    assert response.status_code == 404

    list_response = client.get("/system/secrets")
    assert "encryption-key" in list_response.json()


def test_get_secret_not_found(client):
    """Tests retrieving a non-existent secret returns 404."""
    response = client.get("/system/secrets/nonexistent")
    assert response.status_code == 404


def test_delete_secret(client):
    """Tests deleting a secret from the keystore."""
    client.post("/system/secrets", json={"name": "to-delete", "value": "val"})

    response = client.request("DELETE", "/system/secrets", json={"name": "to-delete"})
    assert response.status_code == 200
    assert "removed" in response.json()["message"]

    response = client.get("/system/secrets")
    assert "to-delete" not in response.json()


def test_delete_secret_not_found(client):
    """Tests deleting a non-existent secret returns 404."""
    response = client.request("DELETE", "/system/secrets", json={"name": "missing"})
    assert response.status_code == 404


def test_update_existing_secret(client):
    """Tests overwriting an existing secret does not error and key remains in list."""
    client.post(
        "/system/secrets", json={"name": " rotating-key ", "value": "old-value"}
    )
    response = client.post(
        "/system/secrets", json={"name": " rotating-key ", "value": "new-value"}
    )
    assert response.status_code == 200

    list_response = client.get("/system/secrets")
    assert " rotating-key " in list_response.json()


# ── Filesystem Browse ──


def test_filesystem_browse_root(client, db_session):
    """Tests browsing the filesystem at ROOT level."""
    db_session.add(models.SystemSetting(key="source_roots", value='["/source_data"]'))
    db_session.commit()

    response = client.get("/system/browse?path=ROOT")
    assert response.status_code == 200
    data = response.json()
    assert len(data["files"]) == 1
    assert data["files"][0]["path"] == "/source_data"
    assert data["files"][0]["type"] == "directory"


def test_filesystem_browse_subdirectory(client, db_session):
    """Tests browsing a subdirectory of the filesystem index."""
    db_session.add(models.SystemSetting(key="source_roots", value='["/source_data"]'))
    db_session.flush()

    file1 = models.FilesystemState(
        file_path="/source_data/subdir/file1.txt", size=100, mtime=1000
    )
    db_session.add(file1)
    db_session.commit()

    response = client.get("/system/browse?path=/source_data/subdir")
    assert response.status_code == 200
    data = response.json()
    assert len(data["files"]) == 1
    assert data["files"][0]["name"] == "file1.txt"
    assert data["files"][0]["type"] == "file"


def test_filesystem_browse_outside_roots(client, db_session):
    """Tests browsing outside configured roots returns 403."""
    db_session.add(models.SystemSetting(key="source_roots", value='["/source_data"]'))
    db_session.commit()

    response = client.get("/system/browse?path=/etc")
    assert response.status_code == 403


# ── Filesystem Search ──


def test_filesystem_search_too_short(client):
    """Tests search with query < 3 chars returns empty list."""
    response = client.get("/system/search?q=ab")
    assert response.status_code == 200
    assert response.json() == []


# ── Hardware Discover ──


def test_discover_hardware_empty(client):
    """Tests hardware discovery endpoint returns a list (may contain real mounts)."""
    response = client.get("/system/hardware/discover")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # Each discovered node should have required fields if present
    for node in data:
        assert "type" in node
        assert "identifier" in node
        assert "is_registered" in node


# ── Hardware Ignore ──


def test_ignore_hardware_duplicate(client):
    """Tests ignoring the same hardware twice is idempotent."""
    client.post("/system/hardware/ignore", json={"identifier": "DISK_DUP"})
    response = client.post("/system/hardware/ignore", json={"identifier": "DISK_DUP"})
    assert response.status_code == 200

    response = client.get("/system/settings")
    assert response.json()["ignored_hardware"].count("DISK_DUP") == 1


def test_update_settings_batch(client):
    """Tests batch updating multiple settings in a single request."""
    response = client.post(
        "/system/settings/batch",
        json={
            "settings": {
                "source_roots": '["/data"]',
                "scan_schedule": "0 2 * * *",
                "redundancy_target": "2",
            }
        },
    )
    assert response.status_code == 200
    assert response.json()["message"] == "3 settings committed."

    # Verify settings were saved
    response = client.get("/system/settings")
    data = response.json()
    assert data["source_roots"] == '["/data"]'
    assert data["scan_schedule"] == "0 2 * * *"
    assert data["redundancy_target"] == "2"


def test_update_settings_batch_empty(client):
    """Tests batch updating with empty settings works."""
    response = client.post("/system/settings/batch", json={"settings": {}})
    assert response.status_code == 200
    assert response.json()["message"] == "0 settings committed."


# ── Database Export ──


def test_database_export(client):
    """Tests database export endpoint returns a SQLite file download."""
    response = client.get("/system/database/export")
    assert response.status_code == 200
    assert "tapehoard_index_" in response.headers["content-disposition"]
    assert ".db" in response.headers["content-disposition"]
    # Should contain SQLite magic bytes
    assert response.content[:16] == b"SQLite format 3\x00"


# ── Tracking Batch ──


def test_batch_track_include(client, db_session):
    """Tests batch tracking include action sets is_ignored=0."""
    file1 = models.FilesystemState(
        file_path="/data/important.txt", size=100, mtime=1000, is_ignored=True
    )
    db_session.add(file1)
    db_session.commit()

    response = client.post(
        "/system/track/batch",
        json={"tracks": ["/data/important.txt"], "untracks": []},
    )
    assert response.status_code == 200
    assert "synchronized" in response.json()["message"]

    db_session.expire_all()
    assert db_session.get(models.FilesystemState, file1.id).is_ignored is False

    # Verify tracked source record was created
    ts = (
        db_session.query(models.TrackedSource)
        .filter_by(path="/data/important.txt")
        .first()
    )
    assert ts is not None
    assert ts.action == "include"


def test_batch_track_exclude(client, db_session):
    """Tests batch tracking exclude action sets is_ignored=1."""
    file1 = models.FilesystemState(
        file_path="/data/temp.txt", size=100, mtime=1000, is_ignored=False
    )
    db_session.add(file1)
    db_session.commit()

    response = client.post(
        "/system/track/batch",
        json={"tracks": [], "untracks": ["/data/temp.txt"]},
    )
    assert response.status_code == 200

    db_session.expire_all()
    assert db_session.get(models.FilesystemState, file1.id).is_ignored is True

    ts = db_session.query(models.TrackedSource).filter_by(path="/data/temp.txt").first()
    assert ts is not None
    assert ts.action == "exclude"


def test_batch_track_empty(client):
    """Tests batch track with empty lists succeeds."""
    response = client.post("/system/track/batch", json={"tracks": [], "untracks": []})
    assert response.status_code == 200


# ── Archive Tree ──


def test_archive_tree_empty(client):
    """Tests archive tree when index is empty."""
    response = client.get("/archive/tree")
    assert response.status_code == 200
    assert response.json() == []


# ── Notifications ──


def test_test_notification_invalid_url(client):
    """Tests test notification with invalid URL returns 500."""
    response = client.post(
        "/system/notifications/test", json={"url": "not-a-valid-url"}
    )
    assert response.status_code == 500
    assert "Failed to dispatch test alert" in response.json()["detail"]


# ── Host Directory Listing ──


def test_ls_traversal_rejected(client):
    """Tests that path traversal attempts are blocked."""
    response = client.get("/system/ls?path=/etc/../secret")
    assert response.status_code == 403
    assert "Path traversal not allowed" in response.json()["detail"]


def test_ls_nonexistent_path(client):
    """Tests listing a non-existent directory returns empty list."""
    response = client.get("/system/ls?path=/nonexistent_path_12345")
    assert response.status_code == 200
    assert response.json() == []


# ── System Tree ──


def test_system_tree_root(client, db_session):
    """Tests system tree at ROOT returns configured source roots."""
    db_session.add(models.SystemSetting(key="source_roots", value='["/source_data"]'))
    db_session.commit()

    response = client.get("/system/tree")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "/source_data"
    assert data[0]["has_children"] is True


def test_system_tree_subdirectory(client, db_session):
    """Tests system tree browsing a subdirectory."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        db_session.add(
            models.SystemSetting(key="source_roots", value=json.dumps([tmpdir]))
        )
        db_session.commit()

        # Create a subdirectory
        import os

        os.makedirs(os.path.join(tmpdir, "subdir"))

        response = client.get(f"/system/tree?path={tmpdir}")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "subdir"


def test_system_tree_outside_roots(client, db_session):
    """Tests tree browsing outside roots returns 403."""
    db_session.add(models.SystemSetting(key="source_roots", value='["/source_data"]'))
    db_session.commit()

    response = client.get("/system/tree?path=/etc")
    assert response.status_code == 403
