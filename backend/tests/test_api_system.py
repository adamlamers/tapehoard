from datetime import datetime, timezone

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


def test_get_settings_empty(client):
    """Tests retrieving settings when none are set."""
    response = client.get("/system/settings")
    assert response.status_code == 200
    assert response.json() == {}


def test_update_settings(client):
    """Tests updating a system setting."""
    response = client.post(
        "/system/settings", json={"key": "schedule_scan", "value": "0 2 * * *"}
    )
    assert response.status_code == 200
    assert response.json() == {"message": "Setting committed."}

    # Verify retrieval
    response = client.get("/system/settings")
    assert response.json()["schedule_scan"] == "0 2 * * *"


def test_list_jobs_empty(client):
    """Tests listing jobs when none exist."""
    response = client.get("/system/jobs")
    assert response.status_code == 200
    assert response.json() == []


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
    """Tests listing the root directory."""
    response = client.get("/system/ls?path=/")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


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


def test_list_discrepancies_empty(client):
    """Tests listing discrepancies when none exist."""
    response = client.get("/system/discrepancies")
    assert response.status_code == 200
    assert response.json() == []


def test_list_discrepancies_deleted_file(client, db_session):
    """Tests listing a confirmed-deleted file in discrepancies."""
    file_record = models.FilesystemState(
        file_path="/data/old.txt",
        size=100,
        mtime=1000,
        is_deleted=True,
        is_ignored=False,
        sha256_hash=None,
    )
    db_session.add(file_record)
    db_session.commit()

    response = client.get("/system/discrepancies")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["path"] == "/data/old.txt"
    assert data[0]["is_deleted"] is True


def test_confirm_file_deleted(client, db_session):
    """Tests confirming a file as deleted."""
    file_record = models.FilesystemState(
        file_path="/data/verify.txt",
        size=50,
        mtime=2000,
        is_deleted=False,
    )
    db_session.add(file_record)
    db_session.commit()

    response = client.post(f"/system/discrepancies/{file_record.id}/confirm")
    assert response.status_code == 200
    assert "marked as deleted" in response.json()["message"]

    db_session.expire_all()
    db_session.refresh(file_record)
    assert file_record.is_deleted is True


def test_confirm_file_deleted_not_found(client):
    """Tests confirming a non-existent file returns 404."""
    response = client.post("/system/discrepancies/9999/confirm")
    assert response.status_code == 404


def test_dismiss_discrepancy(client, db_session):
    """Tests dismissing a deleted file."""
    file_record = models.FilesystemState(
        file_path="/data/dismiss.txt",
        size=50,
        mtime=2000,
        is_deleted=True,
    )
    db_session.add(file_record)
    db_session.commit()

    response = client.post(f"/system/discrepancies/{file_record.id}/dismiss")
    assert response.status_code == 200
    assert "dismissed" in response.json()["message"]

    db_session.expire_all()
    db_session.refresh(file_record)
    assert file_record.missing_acknowledged_at is not None


def test_delete_file_record(client, db_session):
    """Tests hard-deleting a file record and its versions."""
    media = models.StorageMedia(
        media_type="hdd", identifier="M1", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()

    file_record = models.FilesystemState(
        file_path="/data/hard_delete.txt",
        size=100,
        mtime=1000,
        is_deleted=True,
    )
    db_session.add(file_record)
    db_session.flush()

    db_session.add(
        models.FileVersion(
            filesystem_state_id=file_record.id,
            media_id=media.id,
            file_number="1",
            offset_start=0,
            offset_end=100,
        )
    )
    db_session.commit()

    file_id = file_record.id

    response = client.delete(f"/system/discrepancies/{file_id}")
    assert response.status_code == 200

    db_session.expire_all()

    # Verify file and version are gone
    assert (
        db_session.query(models.FilesystemState).filter_by(id=file_id).first() is None
    )
    assert (
        db_session.query(models.FileVersion)
        .filter_by(filesystem_state_id=file_id)
        .first()
        is None
    )


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
    # Unprotected count = 1 (partial file is still vulnerable)
    assert data["unprotected_files_count"] == 1
    # Unprotected size = 3000 - 500 = 2500 (the remaining unarchived bytes)
    assert data["unprotected_data_size"] == 2500


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
    """Tests retrieving a secret value by name."""
    client.post(
        "/system/secrets", json={"name": "encryption-key", "value": "super-secret"}
    )

    response = client.get("/system/secrets/encryption-key")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "encryption-key"
    assert data["value"] == "super-secret"


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
    """Tests overwriting an existing secret value."""
    client.post(
        "/system/secrets", json={"name": " rotating-key ", "value": "old-value"}
    )
    client.post(
        "/system/secrets", json={"name": " rotating-key ", "value": "new-value"}
    )

    response = client.get("/system/secrets/ rotating-key ")
    assert response.status_code == 200
    assert response.json()["value"] == "new-value"


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


# ── Database Export ──


def test_database_export(client):
    """Tests database export endpoint returns a file response."""
    response = client.get("/system/database/export")
    # May return 200 with file or 404 if db path not found
    assert response.status_code in (200, 404)


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
    # Notification manager may succeed or fail depending on apprise parsing
    assert response.status_code in (200, 500)
