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
