from app.db import models


def test_list_archival_history_empty(client):
    """Tests listing backup history when none exist."""
    response = client.get("/backups/")
    assert response.status_code == 200
    assert response.json() == []


def test_trigger_backup_not_found(client):
    """Tests triggering backup for non-existent media."""
    response = client.post("/backups/trigger/999")
    assert response.status_code == 404


def test_trigger_backup_inactive(client, db_session):
    """Tests triggering backup for inactive media."""
    media = models.StorageMedia(
        media_type="hdd", identifier="DISK_INACTIVE", capacity=1000, status="retired"
    )
    db_session.add(media)
    db_session.commit()

    response = client.post(f"/backups/trigger/{media.id}")
    assert response.status_code == 400
    assert "cannot accept new backups" in response.json()["detail"]


def test_trigger_backup_success(client, db_session):
    """Tests triggering a successful backup job."""
    media = models.StorageMedia(
        media_type="hdd", identifier="DISK_ACTIVE", capacity=1000000000, status="active"
    )
    db_session.add(media)
    db_session.commit()

    response = client.post(f"/backups/trigger/{media.id}")
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert data["media"] == "DISK_ACTIVE"

    # Verify job record was created
    job_id = data["job_id"]
    response = client.get(f"/system/jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["job_type"] == "BACKUP"


def test_backup_history_populated(client, db_session):
    """Tests backup history with existing jobs."""
    job = models.Job(job_type="BACKUP", status="COMPLETED")
    db_session.add(job)
    db_session.commit()

    response = client.get("/backups/")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["status"] == "COMPLETED"
