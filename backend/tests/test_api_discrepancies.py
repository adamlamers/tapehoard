from datetime import datetime, timezone

from app.db import models


# ── list_discrepancies ──


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


def test_list_discrepancies_unhashed_missing(client, db_session, tmp_path):
    """Tests listing an unhashed file that is missing from disk."""
    # File path that does not exist on disk
    missing_path = str(tmp_path / "nonexistent" / "file.txt")
    file_record = models.FilesystemState(
        file_path=missing_path,
        size=100,
        mtime=1000,
        sha256_hash=None,
        is_deleted=False,
        is_ignored=False,
    )
    db_session.add(file_record)
    db_session.commit()

    response = client.get("/system/discrepancies")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["path"] == missing_path
    assert data[0]["is_deleted"] is False


def test_list_discrepancies_ignored_excluded(client, db_session):
    """Tests that ignored files are excluded from discrepancies."""
    file_record = models.FilesystemState(
        file_path="/data/ignored.txt",
        size=100,
        mtime=1000,
        is_deleted=True,
        is_ignored=True,
    )
    db_session.add(file_record)
    db_session.commit()

    response = client.get("/system/discrepancies")
    assert response.status_code == 200
    assert response.json() == []


def test_list_discrepancies_acknowledged_excluded(client, db_session):
    """Tests that acknowledged discrepancies are excluded."""
    file_record = models.FilesystemState(
        file_path="/data/dismissed.txt",
        size=100,
        mtime=1000,
        is_deleted=True,
        is_ignored=False,
        missing_acknowledged_at=datetime.now(timezone.utc),
    )
    db_session.add(file_record)
    db_session.commit()

    response = client.get("/system/discrepancies")
    assert response.status_code == 200
    assert response.json() == []


def test_list_discrepancies_has_versions_flag(client, db_session):
    """Tests that has_versions is set based on active/full media."""
    active_media = models.StorageMedia(
        media_type="hdd", identifier="M1", capacity=1000, status="active"
    )
    db_session.add(active_media)
    db_session.flush()

    file1 = models.FilesystemState(
        file_path="/data/deleted_with_backup.txt",
        size=100,
        mtime=1000,
        is_deleted=True,
        is_ignored=False,
    )
    db_session.add(file1)
    db_session.flush()

    db_session.add(
        models.FileVersion(
            filesystem_state_id=file1.id,
            media_id=active_media.id,
            file_number="1",
            offset_start=0,
            offset_end=100,
        )
    )
    db_session.commit()

    response = client.get("/system/discrepancies")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["has_versions"] is True


# ── confirm_discrepancy ──


def test_confirm_discrepancy(client, db_session):
    """Tests confirming a file as deleted."""
    file_record = models.FilesystemState(
        file_path="/data/verify.txt", size=50, mtime=2000, is_deleted=False
    )
    db_session.add(file_record)
    db_session.commit()

    response = client.post(f"/system/discrepancies/{file_record.id}/confirm")
    assert response.status_code == 200
    assert "marked as deleted" in response.json()["message"]

    db_session.expire_all()
    db_session.refresh(file_record)
    assert file_record.is_deleted is True


def test_confirm_discrepancy_not_found(client):
    """Tests confirming a non-existent file returns 404."""
    response = client.post("/system/discrepancies/9999/confirm")
    assert response.status_code == 404


# ── dismiss_discrepancy ──


def test_dismiss_discrepancy(client, db_session):
    """Tests dismissing a deleted file."""
    file_record = models.FilesystemState(
        file_path="/data/dismiss.txt", size=50, mtime=2000, is_deleted=True
    )
    db_session.add(file_record)
    db_session.commit()

    response = client.post(f"/system/discrepancies/{file_record.id}/dismiss")
    assert response.status_code == 200
    assert "dismissed" in response.json()["message"]

    db_session.expire_all()
    db_session.refresh(file_record)
    assert file_record.missing_acknowledged_at is not None


def test_undo_dismiss_discrepancy(client, db_session):
    """Tests undoing a dismissed discrepancy."""
    file_record = models.FilesystemState(
        file_path="/data/undo.txt",
        size=50,
        mtime=2000,
        is_deleted=True,
        missing_acknowledged_at=datetime.now(timezone.utc),
    )
    db_session.add(file_record)
    db_session.commit()

    response = client.post(f"/system/discrepancies/{file_record.id}/undo-dismiss")
    assert response.status_code == 200
    assert "undo" in response.json()["message"].lower()

    db_session.expire_all()
    db_session.refresh(file_record)
    assert file_record.missing_acknowledged_at is None


# ── delete_discrepancy ──


def test_delete_discrepancy_hard_delete(client, db_session):
    """Tests hard-deleting a file record and its versions/cart entries."""
    media = models.StorageMedia(
        media_type="hdd", identifier="M1", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()

    file_record = models.FilesystemState(
        file_path="/data/hard_delete.txt", size=100, mtime=1000, is_deleted=True
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
    db_session.add(models.RestoreCart(filesystem_state_id=file_record.id))
    db_session.commit()

    file_id = file_record.id

    response = client.delete(f"/system/discrepancies/{file_id}")
    assert response.status_code == 200

    db_session.expire_all()
    assert db_session.get(models.FilesystemState, file_id) is None
    assert (
        db_session.query(models.FileVersion)
        .filter_by(filesystem_state_id=file_id)
        .first()
        is None
    )
    assert (
        db_session.query(models.RestoreCart)
        .filter_by(filesystem_state_id=file_id)
        .first()
        is None
    )


def test_delete_discrepancy_not_found(client):
    """Tests deleting a non-existent discrepancy returns 404."""
    response = client.delete("/system/discrepancies/9999")
    assert response.status_code == 404


# ── batch operations ──


def test_batch_confirm_discrepancies(client, db_session):
    """Tests batch confirming files as deleted."""
    file1 = models.FilesystemState(
        file_path="/data/batch1.txt", size=100, mtime=1000, is_deleted=False
    )
    file2 = models.FilesystemState(
        file_path="/data/batch2.txt", size=200, mtime=1000, is_deleted=False
    )
    db_session.add_all([file1, file2])
    db_session.commit()

    response = client.post(
        "/system/discrepancies/batch/confirm",
        json={"ids": [file1.id, file2.id]},
    )
    assert response.status_code == 200
    assert response.json()["count"] == 2

    db_session.expire_all()
    assert db_session.get(models.FilesystemState, file1.id).is_deleted is True
    assert db_session.get(models.FilesystemState, file2.id).is_deleted is True


def test_batch_dismiss_discrepancies(client, db_session):
    """Tests batch dismissing discrepancies."""
    file1 = models.FilesystemState(
        file_path="/data/dismiss1.txt", size=100, mtime=1000, is_deleted=True
    )
    db_session.add(file1)
    db_session.commit()

    response = client.post(
        "/system/discrepancies/batch/dismiss",
        json={"ids": [file1.id]},
    )
    assert response.status_code == 200
    assert response.json()["count"] == 1

    db_session.expire_all()
    assert (
        db_session.get(models.FilesystemState, file1.id).missing_acknowledged_at
        is not None
    )


def test_batch_delete_discrepancies(client, db_session):
    """Tests batch hard-deleting discrepancy records."""
    file1 = models.FilesystemState(
        file_path="/data/del1.txt", size=100, mtime=1000, is_deleted=True
    )
    db_session.add(file1)
    db_session.commit()

    response = client.post(
        "/system/discrepancies/batch/delete",
        json={"ids": [file1.id]},
    )
    assert response.status_code == 200
    assert response.json()["count"] == 1

    db_session.expire_all()
    assert db_session.get(models.FilesystemState, file1.id) is None


def test_batch_resolve_discrepancies(client, db_session):
    """Tests smart batch resolve: recoverable -> queue, lost -> confirm delete."""
    media = models.StorageMedia(
        media_type="hdd", identifier="M1", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()

    # File with backup (recoverable)
    file_recover = models.FilesystemState(
        file_path="/data/recover.txt", size=100, mtime=1000, is_deleted=True
    )
    # File without backup (lost)
    file_lost = models.FilesystemState(
        file_path="/data/lost.txt", size=200, mtime=1000, is_deleted=True
    )
    db_session.add_all([file_recover, file_lost])
    db_session.flush()

    db_session.add(
        models.FileVersion(
            filesystem_state_id=file_recover.id,
            media_id=media.id,
            file_number="1",
            offset_start=0,
            offset_end=100,
        )
    )
    db_session.commit()

    response = client.post(
        "/system/discrepancies/batch/resolve",
        json={"ids": [file_recover.id, file_lost.id]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["recovered_count"] == 1
    assert data["lost_count"] == 1
    assert "/data/recover.txt" in data["recovered_paths"]
    assert "/data/lost.txt" in data["lost_paths"]

    db_session.expire_all()
    # Recoverable should be in restore cart
    assert (
        db_session.query(models.RestoreCart)
        .filter_by(filesystem_state_id=file_recover.id)
        .first()
        is not None
    )
    # Lost should be marked deleted and dismissed
    lost_record = db_session.get(models.FilesystemState, file_lost.id)
    assert lost_record.is_deleted is True
    assert lost_record.missing_acknowledged_at is not None


def test_batch_resolve_by_path_prefix(client, db_session):
    """Tests batch resolve using path_prefix instead of ids."""
    file1 = models.FilesystemState(
        file_path="/data/lost1.txt", size=100, mtime=1000, is_deleted=True
    )
    db_session.add(file1)
    db_session.commit()

    response = client.post(
        "/system/discrepancies/batch/resolve",
        json={"path_prefix": "/data"},
    )
    assert response.status_code == 200
    assert response.json()["lost_count"] == 1


def test_batch_action_no_ids_or_prefix(client):
    """Tests batch actions without ids or path_prefix return 400."""
    for endpoint in ["confirm", "dismiss", "delete", "resolve"]:
        response = client.post(f"/system/discrepancies/batch/{endpoint}", json={})
        assert response.status_code == 400


# ── discrepancy tree ──


def test_discrepancy_tree_empty(client):
    """Tests discrepancy tree when no discrepancies exist."""
    response = client.get("/system/discrepancies/tree")
    assert response.status_code == 200
    assert response.json() == []


def test_discrepancy_tree_root(client, db_session):
    """Tests discrepancy tree at ROOT level."""
    file1 = models.FilesystemState(
        file_path="data/file1.txt", size=100, mtime=1000, is_deleted=True
    )
    db_session.add(file1)
    db_session.commit()

    response = client.get("/system/discrepancies/tree")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 1


# ── discrepancy browse ──


def test_discrepancy_browse_empty(client):
    """Tests discrepancy browse when no discrepancies exist."""
    response = client.get("/system/discrepancies/browse")
    assert response.status_code == 200
    data = response.json()
    assert data["files"] == []


def test_discrepancy_browse_with_files(client, db_session):
    """Tests discrepancy browse returns files and directories."""
    file1 = models.FilesystemState(
        file_path="data/sub/file1.txt", size=100, mtime=1000, is_deleted=True
    )
    db_session.add(file1)
    db_session.commit()

    response = client.get("/system/discrepancies/browse?path=ROOT")
    assert response.status_code == 200
    data = response.json()
    assert "files" in data
