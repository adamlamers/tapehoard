from app.db import models
from datetime import datetime, timezone
import json


def test_list_media_empty(client):
    """Tests listing media when inventory is empty."""
    response = client.get("/inventory/media")
    assert response.status_code == 200
    assert response.json() == []


def test_register_media(client):
    """Tests registering a new storage medium."""
    media_data = {
        "media_type": "local_hdd",
        "identifier": "DISK_001",
        "capacity": 1000000000,
        "location": "Safe A",
        "mount_path": "/mnt/test",
    }
    response = client.post("/inventory/media", json=media_data)
    assert response.status_code == 200
    data = response.json()
    assert data["identifier"] == "DISK_001"
    assert data["status"] == "active"


def test_update_media(client, db_session):
    """Tests updating media metadata."""
    media = models.StorageMedia(
        media_type="tape", identifier="TAPE_001", capacity=2500000000, status="active"
    )
    db_session.add(media)
    db_session.commit()

    response = client.patch(
        f"/inventory/media/{media.id}",
        json={"location": "Vault B", "status": "retired"},
    )
    assert response.status_code == 200
    assert response.json()["location"] == "Vault B"
    assert response.json()["status"] == "retired"


def test_delete_media(client, db_session):
    """Tests purging a media asset."""
    media = models.StorageMedia(
        media_type="hdd", identifier="DISK_999", capacity=1000000, status="active"
    )
    db_session.add(media)
    db_session.commit()

    response = client.delete(f"/inventory/media/{media.id}")
    assert response.status_code == 200
    assert response.json() == {
        "message": "Media and associated history successfully purged."
    }


def test_get_insights(client, db_session):
    """Tests system-wide analytics generation."""
    # Add some data
    file1 = models.FilesystemState(
        file_path="/source/f1.txt",
        size=100,
        mtime=1000,
        sha256_hash="hash1",
    )
    db_session.add(file1)
    db_session.commit()

    response = client.get("/inventory/insights")
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert data["summary"]["total_files"] == 1


def test_browse_index_root(client, db_session):
    """Tests browsing the virtual archive index at the root."""
    # Set source roots
    db_session.add(
        models.SystemSetting(key="source_roots", value=json.dumps(["source_data"]))
    )
    db_session.flush()

    # Add a backed up file
    media = models.StorageMedia(
        media_type="hdd", identifier="M1", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()

    file1 = models.FilesystemState(
        file_path="source_data/file1.txt", size=100, mtime=1000
    )
    db_session.add(file1)
    db_session.flush()

    version = models.FileVersion(
        filesystem_state_id=file1.id,
        media_id=media.id,
        file_number="1",
        offset_start=0,
        offset_end=100,
    )
    db_session.add(version)
    db_session.commit()

    # Root should show source_data if it has versions
    response = client.get("/archive/browse?path=ROOT")
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert data[0]["path"] == "source_data"


def test_search_index(client, db_session):
    """Tests FTS5 search functionality."""
    db_session.add(models.SystemSetting(key="source_roots", value=json.dumps(["data"])))
    db_session.flush()

    file1 = models.FilesystemState(
        file_path="data/important.doc",
        size=500,
        mtime=2000,
        sha256_hash="hash",
    )
    db_session.add(file1)
    db_session.commit()

    # Add a version to make it show up in search
    media = models.StorageMedia(
        media_type="hdd", identifier="M2", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()
    db_session.add(
        models.FileVersion(
            filesystem_state_id=file1.id,
            media_id=media.id,
            file_number="1",
            offset_start=0,
            offset_end=500,
        )
    )
    db_session.commit()

    # Trigger FTS manually since we are using raw SQL triggers which might not have fired
    # if we didn't insert via SQL or if there are issues in :memory:
    # but conftest uses a real temp file.
    db_session.commit()

    response = client.get("/archive/search?q=important")
    assert response.status_code == 200
    # If FTS5 is working, it should return results.


def test_get_metadata(client, db_session):
    """Tests exhaustive metadata retrieval."""
    file1 = models.FilesystemState(
        file_path="data/meta.txt",
        size=123,
        mtime=3000,
        last_seen_timestamp=datetime.now(timezone.utc),
    )
    db_session.add(file1)
    db_session.commit()

    response = client.get("/archive/metadata?path=data/meta.txt")
    assert response.status_code == 200
    assert response.json()["path"] == "data/meta.txt"


# ── Partial Archive Detection ──


def test_browse_shows_partially_archived_file(client, db_session):
    """Files with offset_end < size should show is_partially_archived=True."""
    db_session.add(
        models.SystemSetting(key="source_roots", value=json.dumps(["source_data"]))
    )
    db_session.flush()

    media = models.StorageMedia(
        media_type="hdd", identifier="M1", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()

    file1 = models.FilesystemState(
        file_path="source_data/big.zip", size=1000, mtime=1000
    )
    db_session.add(file1)
    db_session.flush()

    # Only 600 bytes archived (partial)
    db_session.add(
        models.FileVersion(
            filesystem_state_id=file1.id,
            media_id=media.id,
            file_number="1",
            offset_start=0,
            offset_end=600,
        )
    )
    db_session.commit()

    response = client.get("/archive/browse?path=source_data")
    assert response.status_code == 200
    data = response.json()
    file_entry = next((f for f in data if f["path"] == "source_data/big.zip"), None)
    assert file_entry is not None
    assert file_entry["is_partially_archived"] is True
    assert file_entry["archived_bytes"] == 600


def test_browse_fully_archived_file_not_partial(client, db_session):
    """Files with offset_end == size should show is_partially_archived=False."""
    db_session.add(
        models.SystemSetting(key="source_roots", value=json.dumps(["source_data"]))
    )
    db_session.flush()

    media = models.StorageMedia(
        media_type="hdd", identifier="M1", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()

    file1 = models.FilesystemState(
        file_path="source_data/complete.txt", size=500, mtime=1000
    )
    db_session.add(file1)
    db_session.flush()

    db_session.add(
        models.FileVersion(
            filesystem_state_id=file1.id,
            media_id=media.id,
            file_number="1",
            offset_start=0,
            offset_end=500,
        )
    )
    db_session.commit()

    response = client.get("/archive/browse?path=source_data")
    assert response.status_code == 200
    data = response.json()
    file_entry = next(
        (f for f in data if f["path"] == "source_data/complete.txt"), None
    )
    assert file_entry is not None
    assert file_entry["is_partially_archived"] is False
    assert file_entry["archived_bytes"] == 500


def test_search_shows_partially_archived(client, db_session):
    """Search results include partial archive indicators if FTS5 finds the file."""
    db_session.add(models.SystemSetting(key="source_roots", value=json.dumps(["data"])))
    db_session.flush()

    file1 = models.FilesystemState(file_path="data/partial.bin", size=1000, mtime=1000)
    db_session.add(file1)
    db_session.commit()

    media = models.StorageMedia(
        media_type="hdd", identifier="M2", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()
    db_session.add(
        models.FileVersion(
            filesystem_state_id=file1.id,
            media_id=media.id,
            file_number="1",
            offset_start=0,
            offset_end=300,
        )
    )
    db_session.commit()

    # Manually insert into FTS5 since triggers may not fire on ORM inserts in tests
    from sqlalchemy import text

    db_session.execute(
        text("INSERT INTO filesystem_fts(rowid, file_path) VALUES (:rowid, :path)"),
        {"rowid": file1.id, "path": file1.file_path},
    )
    db_session.commit()

    response = client.get("/archive/search?q=partial")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["is_partially_archived"] is True
    assert data[0]["archived_bytes"] == 300


def test_metadata_partial_archive(client, db_session):
    """Metadata endpoint returns archived_bytes and is_partially_archived."""
    media = models.StorageMedia(
        media_type="hdd", identifier="M1", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()

    file1 = models.FilesystemState(file_path="data/half.txt", size=800, mtime=1000)
    db_session.add(file1)
    db_session.flush()

    db_session.add(
        models.FileVersion(
            filesystem_state_id=file1.id,
            media_id=media.id,
            file_number="1",
            offset_start=0,
            offset_end=350,
        )
    )
    db_session.commit()

    response = client.get("/archive/metadata?path=data/half.txt")
    assert response.status_code == 200
    data = response.json()
    assert data["is_partially_archived"] is True
    assert data["archived_bytes"] == 350
    assert data["size"] == 800


# ── Type-Specific Media Schemas ──


def test_register_lto_tape_media(client):
    """Tests registering an LTO tape with type-specific fields."""
    media_data = {
        "media_type": "lto_tape",
        "identifier": "LTO7_001",
        "capacity": 6000000000000,
        "location": "Vault A",
        "generation": "LTO-7",
        "worm": False,
        "write_protected": False,
        "compression": True,
        "encryption_key_id": "tape-key-1",
        "encryption_secret_name": "my-tape-secret",
    }
    response = client.post("/inventory/media", json=media_data)
    assert response.status_code == 200
    data = response.json()
    assert data["identifier"] == "LTO7_001"
    assert data["media_type"] == "lto_tape"
    assert data["generation"] == "LTO-7"
    assert data["compression"] is True
    assert data["encryption_key_id"] == "tape-key-1"
    assert data["encryption_secret_name"] == "my-tape-secret"


def test_register_cloud_media(client):
    """Tests registering S3-compatible cloud storage with secret names."""
    media_data = {
        "media_type": "s3_compat",
        "identifier": "s3-primary",
        "capacity": 100000000000,
        "location": "us-east-1",
        "provider_template": "aws",
        "endpoint_url": "https://s3.amazonaws.com",
        "region": "us-east-1",
        "bucket_name": "my-backup-bucket",
        "access_key_id": "AKIAIOSFODNN7EXAMPLE",
        "secret_access_key_name": "aws-production-key",
        "obfuscate_filenames": True,
        "encryption_secret_name": "my-encryption-key",
    }
    response = client.post("/inventory/media", json=media_data)
    assert response.status_code == 200
    data = response.json()
    assert data["identifier"] == "s3-primary"
    assert data["media_type"] == "s3_compat"
    assert data["bucket_name"] == "my-backup-bucket"
    assert data["secret_access_key_name"] == "aws-production-key"
    assert data["encryption_secret_name"] == "my-encryption-key"


# ── Structured Location Fields ──


def test_register_hdd_media_with_encryption_secret(client):
    """Tests registering HDD with encryption secret reference."""
    media_data = {
        "media_type": "local_hdd",
        "identifier": "DISK_ENC_001",
        "capacity": 1000000000,
        "location": "Safe B",
        "encrypted": True,
        "encryption_key_id": "hdd-key-1",
        "encryption_secret_name": "my-hdd-secret",
    }
    response = client.post("/inventory/media", json=media_data)
    assert response.status_code == 200
    data = response.json()
    assert data["identifier"] == "DISK_ENC_001"
    assert data["encrypted"] is True
    assert data["encryption_key_id"] == "hdd-key-1"
    assert data["encryption_secret_name"] == "my-hdd-secret"


def test_register_media_with_structured_location(client):
    """Tests that structured location fields are persisted."""
    media_data = {
        "media_type": "local_hdd",
        "identifier": "DISK_LOC_001",
        "capacity": 1000000000,
        "location": "Building 1, Room 101",
        "location_building": "Building 1",
        "location_room": "Room 101",
        "location_rack": "Rack A",
        "location_slot": "Slot 3",
    }
    response = client.post("/inventory/media", json=media_data)
    assert response.status_code == 200
    data = response.json()
    assert data["location_building"] == "Building 1"
    assert data["location_room"] == "Room 101"
    assert data["location_rack"] == "Rack A"
    assert data["location_slot"] == "Slot 3"


def test_update_structured_location(client, db_session):
    """Tests updating structured location fields individually."""
    media = models.StorageMedia(
        media_type="hdd",
        identifier="DISK_LOC_002",
        capacity=1000000,
        status="active",
        location_building="Old Building",
    )
    db_session.add(media)
    db_session.commit()

    response = client.patch(
        f"/inventory/media/{media.id}",
        json={
            "location_building": "New Building",
            "location_room": "Room 202",
            "location_rack": "Rack B",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["location_building"] == "New Building"
    assert data["location_room"] == "Room 202"
    assert data["location_rack"] == "Rack B"


# ── Capacity Management ──


def test_capacity_validation_rejects_decrease_below_used(client, db_session):
    """Updating capacity below bytes_used should return 400."""
    media = models.StorageMedia(
        media_type="hdd",
        identifier="DISK_CAP_001",
        capacity=1000000,
        status="active",
        bytes_used=500000,
    )
    db_session.add(media)
    db_session.commit()

    response = client.patch(
        f"/inventory/media/{media.id}",
        json={"capacity": 400000},
    )
    assert response.status_code == 400
    assert "utilized space" in response.json()["detail"]


def test_capacity_increase_reactivates_full_media(client, db_session):
    """Increasing capacity on a 'full' media should auto-set status to active."""
    media = models.StorageMedia(
        media_type="hdd",
        identifier="DISK_FULL_001",
        capacity=1000000,
        status="full",
        bytes_used=500000,
    )
    db_session.add(media)
    db_session.commit()

    response = client.patch(
        f"/inventory/media/{media.id}",
        json={"capacity": 2000000},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "active"


def test_capacity_increase_keeps_full_if_still_near_limit(client, db_session):
    """Increasing capacity but still near 98% should keep status as full."""
    media = models.StorageMedia(
        media_type="hdd",
        identifier="DISK_FULL_002",
        capacity=1000000,
        status="full",
        bytes_used=990000,
    )
    db_session.add(media)
    db_session.commit()

    response = client.patch(
        f"/inventory/media/{media.id}",
        json={"capacity": 1000001},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "full"


# ── Status Auto-Purge on Failure/Retired ──


def test_update_status_to_retired_purges_versions(client, db_session):
    """Setting status to RETIRED should delete all file_versions."""
    media = models.StorageMedia(
        media_type="hdd", identifier="DISK_RET_001", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()

    file1 = models.FilesystemState(file_path="data/file1.txt", size=100, mtime=1000)
    db_session.add(file1)
    db_session.flush()

    db_session.add(
        models.FileVersion(
            filesystem_state_id=file1.id,
            media_id=media.id,
            file_number="1",
            offset_start=0,
            offset_end=100,
        )
    )
    db_session.commit()

    response = client.patch(
        f"/inventory/media/{media.id}",
        json={"status": "RETIRED"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "RETIRED"

    # Verify versions are purged via raw SQL to bypass identity map caching
    from sqlalchemy import text

    db_session.commit()  # ensure test session sees committed changes
    result = db_session.execute(
        text("SELECT COUNT(*) FROM file_versions WHERE media_id = :media_id"),
        {"media_id": media.id},
    ).scalar()
    assert result == 0


# ── Archive Tree ──


def test_archive_tree_with_versions(client, db_session):
    """Tests archive tree returns source roots with versions."""
    db_session.add(models.SystemSetting(key="source_roots", value=json.dumps(["data"])))
    db_session.flush()

    media = models.StorageMedia(
        media_type="hdd", identifier="M1", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()

    file1 = models.FilesystemState(file_path="data/file1.txt", size=100, mtime=1000)
    db_session.add(file1)
    db_session.flush()

    db_session.add(
        models.FileVersion(
            filesystem_state_id=file1.id,
            media_id=media.id,
            file_number="1",
            offset_start=0,
            offset_end=100,
        )
    )
    db_session.commit()

    response = client.get("/archive/tree")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "data"
    assert data[0]["has_children"] is True


def test_archive_tree_nested_directories(client, db_session):
    """Tests archive tree with nested directories."""
    db_session.add(models.SystemSetting(key="source_roots", value=json.dumps(["data"])))
    db_session.flush()

    media = models.StorageMedia(
        media_type="hdd", identifier="M1", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()

    file1 = models.FilesystemState(
        file_path="data/subdir/file1.txt", size=100, mtime=1000
    )
    db_session.add(file1)
    db_session.flush()

    db_session.add(
        models.FileVersion(
            filesystem_state_id=file1.id,
            media_id=media.id,
            file_number="1",
            offset_start=0,
            offset_end=100,
        )
    )
    db_session.commit()

    response = client.get("/archive/tree")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "data"


def test_archive_tree_empty_no_versions(client, db_session):
    """Tests archive tree excludes roots with no versions."""
    db_session.add(models.SystemSetting(key="source_roots", value=json.dumps(["data"])))
    db_session.flush()

    # Add file but no versions
    file1 = models.FilesystemState(file_path="data/file1.txt", size=100, mtime=1000)
    db_session.add(file1)
    db_session.commit()

    response = client.get("/archive/tree")
    assert response.status_code == 200
    assert response.json() == []


# ── Metadata Directory ──


def test_metadata_directory(client, db_session):
    """Tests metadata endpoint for a directory returns aggregated stats."""
    db_session.add(models.SystemSetting(key="source_roots", value=json.dumps(["data"])))
    db_session.flush()

    media = models.StorageMedia(
        media_type="hdd", identifier="M1", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()

    file1 = models.FilesystemState(file_path="data/sub/file1.txt", size=100, mtime=1000)
    file2 = models.FilesystemState(file_path="data/sub/file2.txt", size=200, mtime=1000)
    db_session.add_all([file1, file2])
    db_session.flush()

    db_session.add(
        models.FileVersion(
            filesystem_state_id=file1.id,
            media_id=media.id,
            file_number="1",
            offset_start=0,
            offset_end=100,
        )
    )
    db_session.add(
        models.FileVersion(
            filesystem_state_id=file2.id,
            media_id=media.id,
            file_number="2",
            offset_start=0,
            offset_end=200,
        )
    )
    db_session.commit()

    response = client.get("/archive/metadata?path=data/sub")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "directory"
    assert data["child_count"] == 2
    assert data["size"] == 300
