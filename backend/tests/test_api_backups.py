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


def test_trigger_backup_already_running(client, db_session):
    """Tests triggering backup when one is already active returns 400."""
    media = models.StorageMedia(
        media_type="hdd", identifier="DISK_1", capacity=1000, status="active"
    )
    db_session.add(media)
    db_session.flush()

    # Create an active backup job
    active_job = models.Job(job_type="BACKUP", status="RUNNING", is_cancelled=False)
    db_session.add(active_job)
    db_session.commit()

    response = client.post(f"/backups/trigger/{media.id}")
    assert response.status_code == 400
    assert "already running" in response.json()["detail"]


def test_trigger_auto_backup_no_media(client):
    """Tests auto backup with no active media returns 400."""
    response = client.post("/backups/trigger/auto")
    assert response.status_code == 400
    assert "No active media" in response.json()["detail"]


def test_trigger_auto_backup_already_running(client, db_session):
    """Tests auto backup when one is already active returns 400."""
    active_job = models.Job(job_type="BACKUP", status="PENDING", is_cancelled=False)
    db_session.add(active_job)
    db_session.commit()

    response = client.post("/backups/trigger/auto")
    assert response.status_code == 400
    assert "already running" in response.json()["detail"]


def test_trigger_auto_backup_success(client, db_session):
    """Tests triggering auto backup creates a job."""
    media = models.StorageMedia(
        media_type="hdd", identifier="AUTO_DISK", capacity=1000000000, status="active"
    )
    db_session.add(media)
    db_session.commit()

    response = client.post("/backups/trigger/auto")
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert "Auto-archival job submitted" in data["message"]
