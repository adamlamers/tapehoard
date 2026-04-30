from app.db import models
import json


def test_list_recovery_queue_empty(client):
    """Tests listing restore queue when empty."""
    response = client.get("/restores/queue")
    assert response.status_code == 200
    assert response.json() == []


def test_add_file_to_recovery_queue(client, db_session):
    """Tests adding a file to the recovery queue."""
    # Setup: Media, File, and a Version (required for restore)
    media = models.StorageMedia(
        media_type="hdd", identifier="M1", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()

    file_record = models.FilesystemState(
        file_path="/data/file.txt", size=100, mtime=1000
    )
    db_session.add(file_record)
    db_session.flush()

    version = models.FileVersion(
        filesystem_state_id=file_record.id,
        media_id=media.id,
        file_number="1",
        offset_start=0,
        offset_end=100,
    )
    db_session.add(version)
    db_session.commit()

    response = client.post(f"/restores/queue/file/{file_record.id}")
    assert response.status_code == 200
    assert response.json() == {"message": "Added to recovery queue."}

    # Verify in queue
    response = client.get("/restores/queue")
    assert len(response.json()) == 1
    assert response.json()[0]["file_path"] == "/data/file.txt"


def test_add_file_no_version(client, db_session):
    """Tests adding a file with no backed up versions fails."""
    file_record = models.FilesystemState(
        file_path="/data/unprotected.txt", size=100, mtime=1000
    )
    db_session.add(file_record)
    db_session.commit()

    response = client.post(f"/restores/queue/file/{file_record.id}")
    assert response.status_code == 400
    assert "no backed up versions" in response.json()["detail"]


def test_clear_recovery_queue(client, db_session):
    """Tests clearing the queue."""
    file_record = models.FilesystemState(file_path="/data/f.txt", size=10, mtime=1)
    db_session.add(file_record)
    db_session.flush()
    db_session.add(models.RestoreCart(filesystem_state_id=file_record.id))
    db_session.commit()

    response = client.post("/restores/queue/clear")
    assert response.status_code == 200

    # Verify empty
    response = client.get("/restores/queue")
    assert response.json() == []


def test_remove_from_recovery_queue(client, db_session):
    """Tests removing a specific item from queue."""
    file_record = models.FilesystemState(file_path="/data/delete.txt", size=10, mtime=1)
    db_session.add(file_record)
    db_session.flush()
    cart_item = models.RestoreCart(filesystem_state_id=file_record.id)
    db_session.add(cart_item)
    db_session.commit()

    response = client.delete(f"/restores/queue/item/{cart_item.id}")
    assert response.status_code == 200

    # Verify empty
    response = client.get("/restores/queue")
    assert response.json() == []


def test_add_directory_to_recovery_queue(client, db_session):
    """Tests recursive directory add to queue."""
    media = models.StorageMedia(
        media_type="hdd", identifier="M2", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()

    file1 = models.FilesystemState(file_path="/source/dir/a.txt", size=50, mtime=1)
    file2 = models.FilesystemState(file_path="/source/dir/b.txt", size=50, mtime=1)
    db_session.add_all([file1, file2])
    db_session.flush()

    db_session.add(
        models.FileVersion(
            filesystem_state_id=file1.id,
            media_id=media.id,
            file_number="1",
            offset_start=0,
            offset_end=50,
        )
    )
    db_session.add(
        models.FileVersion(
            filesystem_state_id=file2.id,
            media_id=media.id,
            file_number="1",
            offset_start=0,
            offset_end=50,
        )
    )
    db_session.commit()

    response = client.post("/restores/queue/directory", json={"path": "/source/dir"})
    assert response.status_code == 200

    # Verify both files are in queue
    response = client.get("/restores/queue")
    assert len(response.json()) == 2


def test_calculate_manifest(client, db_session):
    """Tests the physical media manifest generation."""
    media = models.StorageMedia(
        media_type="tape", identifier="T001", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()

    file1 = models.FilesystemState(file_path="/source/data.bin", size=500, mtime=1)
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
    db_session.add(models.RestoreCart(filesystem_state_id=file1.id))
    db_session.commit()

    response = client.get("/restores/manifest")
    assert response.status_code == 200
    data = response.json()
    assert data["total_files"] == 1
    assert data["total_size"] == 500
    assert data["media_required"][0]["identifier"] == "T001"


def test_trigger_recovery(client, db_session, tmp_path):
    """Tests initiating a recovery job."""
    file_record = models.FilesystemState(file_path="/data/file.txt", size=10, mtime=1)
    db_session.add(file_record)
    db_session.flush()
    db_session.add(models.RestoreCart(filesystem_state_id=file_record.id))
    db_session.commit()

    dest = tmp_path / "recovery"
    dest.mkdir()

    response = client.post("/restores/trigger", json={"destination_path": str(dest)})
    assert response.status_code == 200
    assert "job_id" in response.json()


def test_browse_queue_virtual_fs(client, db_session):
    """Tests the virtual FS view of the queue."""
    db_session.add(
        models.SystemSetting(key="source_roots", value=json.dumps(["/source"]))
    )
    file_record = models.FilesystemState(
        file_path="/source/dir/file.txt", size=10, mtime=1
    )
    db_session.add(file_record)
    db_session.flush()
    db_session.add(models.RestoreCart(filesystem_state_id=file_record.id))
    db_session.commit()

    # Root browse
    response = client.get("/restores/queue/browse?path=ROOT")
    assert response.status_code == 200
    assert response.json()[0]["path"] == "/source"

    # Folder browse
    response = client.get("/restores/queue/browse?path=/source/dir")
    assert response.status_code == 200
    assert response.json()[0]["name"] == "file.txt"


def test_deleted_file_rejected_from_restore_queue(client, db_session):
    """Tests that a deleted file cannot be added to the recovery queue."""
    media = models.StorageMedia(
        media_type="hdd", identifier="M1", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()

    file_record = models.FilesystemState(
        file_path="/data/deleted.txt", size=100, mtime=1000, is_deleted=True
    )
    db_session.add(file_record)
    db_session.flush()

    version = models.FileVersion(
        filesystem_state_id=file_record.id,
        media_id=media.id,
        file_number="1",
        offset_start=0,
        offset_end=100,
    )
    db_session.add(version)
    db_session.commit()

    response = client.post(f"/restores/queue/file/{file_record.id}")
    assert response.status_code == 400
    assert "marked as deleted" in response.json()["detail"]


def test_manifest_excludes_deleted_files(client, db_session):
    """Tests that deleted files are excluded from the restore manifest."""
    media = models.StorageMedia(
        media_type="tape", identifier="T001", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()

    active_file = models.FilesystemState(
        file_path="/source/keep.bin", size=500, mtime=1, is_deleted=False
    )
    deleted_file = models.FilesystemState(
        file_path="/source/gone.bin", size=500, mtime=1, is_deleted=True
    )
    db_session.add_all([active_file, deleted_file])
    db_session.flush()

    db_session.add(
        models.FileVersion(
            filesystem_state_id=active_file.id,
            media_id=media.id,
            file_number="1",
            offset_start=0,
            offset_end=500,
        )
    )
    db_session.add(
        models.FileVersion(
            filesystem_state_id=deleted_file.id,
            media_id=media.id,
            file_number="2",
            offset_start=0,
            offset_end=500,
        )
    )
    db_session.add(models.RestoreCart(filesystem_state_id=active_file.id))
    db_session.add(models.RestoreCart(filesystem_state_id=deleted_file.id))
    db_session.commit()

    response = client.get("/restores/manifest")
    assert response.status_code == 200
    data = response.json()
    assert data["total_files"] == 1
    assert data["total_size"] == 500
