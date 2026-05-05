from datetime import datetime, timedelta, timezone

import pytest

from app.db import models


# ── list_jobs ──


def test_list_jobs_empty(client):
    """Tests listing jobs when none exist."""
    response = client.get("/system/jobs")
    assert response.status_code == 200
    assert response.json() == []


def test_list_jobs_populated(client, db_session):
    """Tests listing jobs with pagination and latest_log inclusion."""
    now = datetime.now(timezone.utc)
    job1 = models.Job(
        job_type="SCAN",
        status="COMPLETED",
        progress=100.0,
        current_task="Done",
        started_at=now - timedelta(seconds=2),
        completed_at=now - timedelta(seconds=1),
        created_at=now - timedelta(seconds=2),
    )
    job2 = models.Job(
        job_type="BACKUP",
        status="RUNNING",
        progress=50.0,
        current_task="Writing archive",
        created_at=now,
    )
    db_session.add_all([job1, job2])
    db_session.flush()

    db_session.add(models.JobLog(job_id=job1.id, message="Scan complete"))
    db_session.add(models.JobLog(job_id=job2.id, message="Processing chunk 3"))
    db_session.commit()

    response = client.get("/system/jobs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # Most recent first (job2)
    assert data[0]["job_type"] == "BACKUP"
    assert data[0]["status"] == "RUNNING"
    assert data[0]["latest_log"] == "Processing chunk 3"
    assert data[1]["job_type"] == "SCAN"
    assert data[1]["latest_log"] == "Scan complete"


def test_list_jobs_pagination(client, db_session):
    """Tests limit/offset pagination on jobs list."""
    for i in range(5):
        db_session.add(models.Job(job_type="SCAN", status="COMPLETED"))
    db_session.commit()

    response = client.get("/system/jobs?limit=2&offset=1")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


# ── get_job_count ──


def test_get_job_count_empty(client):
    """Tests job count when none exist."""
    response = client.get("/system/jobs/count")
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_get_job_count_populated(client, db_session):
    """Tests job count with existing jobs."""
    db_session.add_all(
        [
            models.Job(job_type="SCAN", status="COMPLETED"),
            models.Job(job_type="BACKUP", status="FAILED"),
        ]
    )
    db_session.commit()

    response = client.get("/system/jobs/count")
    assert response.status_code == 200
    assert response.json()["count"] == 2


# ── get_job_stats ──


def test_get_job_stats_empty(client):
    """Tests job stats when database is empty."""
    response = client.get("/system/jobs/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["success_rate"] == 100.0
    assert data["avg_duration_seconds"] == 0


def test_get_job_stats_populated(client, db_session):
    """Tests job stats with a mix of statuses and types."""
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            models.Job(
                job_type="SCAN",
                status="COMPLETED",
                started_at=now,
                completed_at=now,
            ),
            models.Job(
                job_type="SCAN",
                status="COMPLETED",
                started_at=now,
                completed_at=now,
            ),
            models.Job(job_type="BACKUP", status="FAILED"),
            models.Job(job_type="RESTORE", status="RUNNING"),
            models.Job(job_type="SCAN", status="PENDING"),
        ]
    )
    db_session.commit()

    response = client.get("/system/jobs/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 5
    assert data["completed"] == 2
    assert data["failed"] == 1
    assert data["running"] == 1
    assert data["pending"] == 1
    # 2 completed / (2 completed + 1 failed) = 66.7%
    assert data["success_rate"] == 66.7
    assert data["job_type_counts"]["SCAN"] == 3
    assert data["job_type_counts"]["BACKUP"] == 1
    assert data["job_type_counts"]["RESTORE"] == 1


# ── get_job ──


def test_get_job_found(client, db_session):
    """Tests retrieving a specific job by ID."""
    job = models.Job(
        job_type="BACKUP",
        status="RUNNING",
        progress=42.5,
        current_task="Archiving files",
    )
    db_session.add(job)
    db_session.flush()
    db_session.add(models.JobLog(job_id=job.id, message="Started backup"))
    db_session.commit()

    response = client.get(f"/system/jobs/{job.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == job.id
    assert data["job_type"] == "BACKUP"
    assert data["status"] == "RUNNING"
    assert data["progress"] == 42.5
    assert data["current_task"] == "Archiving files"
    assert data["latest_log"] == "Started backup"


def test_get_job_not_found(client):
    """Tests retrieving a non-existent job returns 404."""
    response = client.get("/system/jobs/99999")
    assert response.status_code == 404


# ── get_job_logs ──


def test_get_job_logs_found(client, db_session):
    """Tests retrieving logs for a specific job."""
    job = models.Job(job_type="SCAN", status="COMPLETED")
    db_session.add(job)
    db_session.flush()
    db_session.add(models.JobLog(job_id=job.id, message="Step 1"))
    db_session.add(models.JobLog(job_id=job.id, message="Step 2"))
    db_session.commit()

    response = client.get(f"/system/jobs/{job.id}/logs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["message"] == "Step 1"
    assert data[1]["message"] == "Step 2"


def test_get_job_logs_not_found(client):
    """Tests retrieving logs for a non-existent job returns 404."""
    response = client.get("/system/jobs/99999/logs")
    assert response.status_code == 404


# ── cancel_job ──


def test_cancel_running_job(client, db_session):
    """Tests cancelling a running job sets FAILED + is_cancelled."""
    job = models.Job(job_type="BACKUP", status="RUNNING")
    db_session.add(job)
    db_session.commit()

    response = client.post(f"/system/jobs/{job.id}/cancel")
    assert response.status_code == 200
    assert "Cancellation request submitted" in response.json()["message"]

    db_session.expire_all()
    refreshed = db_session.get(models.Job, job.id)
    assert refreshed.status == "FAILED"
    assert refreshed.is_cancelled is True
    assert "Cancelled" in refreshed.error_message


def test_cancel_pending_job(client, db_session):
    """Tests cancelling a pending job."""
    job = models.Job(job_type="SCAN", status="PENDING")
    db_session.add(job)
    db_session.commit()

    response = client.post(f"/system/jobs/{job.id}/cancel")
    assert response.status_code == 200

    db_session.expire_all()
    refreshed = db_session.get(models.Job, job.id)
    assert refreshed.status == "FAILED"
    assert refreshed.is_cancelled is True


def test_cancel_completed_job_is_noop(client, db_session):
    """Tests cancelling a completed job is a no-op (cancel only acts on PENDING/RUNNING)."""
    job = models.Job(job_type="SCAN", status="COMPLETED")
    db_session.add(job)
    db_session.commit()

    response = client.post(f"/system/jobs/{job.id}/cancel")
    assert response.status_code == 200

    db_session.expire_all()
    refreshed = db_session.get(models.Job, job.id)
    # cancel_job only acts on PENDING/RUNNING jobs
    assert refreshed.status == "COMPLETED"
    assert refreshed.is_cancelled is False


def test_complete_job_skips_already_failed_job(db_session):
    """Tests that complete_job is a no-op when the job was cancelled/failed."""
    from app.services.scanner import JobManager

    job = models.Job(job_type="BACKUP", status="FAILED", is_cancelled=True)
    db_session.add(job)
    db_session.commit()

    JobManager.complete_job(job.id)

    db_session.expire_all()
    refreshed = db_session.get(models.Job, job.id)
    assert refreshed.status == "FAILED"
    assert refreshed.is_cancelled is True
    assert refreshed.progress == 0.0


def test_fail_job_skips_already_failed_job(db_session):
    """Tests that fail_job preserves the original error when job is already failed."""
    from app.services.scanner import JobManager

    job = models.Job(job_type="BACKUP", status="FAILED", error_message="Original error")
    db_session.add(job)
    db_session.commit()

    JobManager.fail_job(job.id, "New error message")

    db_session.expire_all()
    refreshed = db_session.get(models.Job, job.id)
    assert refreshed.status == "FAILED"
    assert refreshed.error_message == "Original error"


def test_complete_job_skips_deleted_job(db_session):
    """Tests that complete_job handles a job deleted by test reset gracefully."""
    from app.services.scanner import JobManager

    job = models.Job(job_type="SCAN", status="RUNNING")
    db_session.add(job)
    db_session.commit()
    job_id = job.id

    # Simulate /system/test/reset deleting the job
    db_session.query(models.Job).filter(models.Job.id == job_id).delete()
    db_session.commit()

    # Should not raise
    JobManager.complete_job(job_id)

    assert db_session.get(models.Job, job_id) is None


# ── retry_job ──


def test_retry_failed_scan_job(client, db_session):
    """Tests retrying a failed SCAN job creates a new job."""
    job = models.Job(job_type="SCAN", status="FAILED", error_message="Timeout")
    db_session.add(job)
    db_session.commit()

    response = client.post(f"/system/jobs/{job.id}/retry")
    assert response.status_code == 200
    data = response.json()
    assert "Retry initiated" in data["message"]
    assert "new_job_id" in data

    # Verify new job exists with correct type
    new_job = db_session.get(models.Job, data["new_job_id"])
    assert new_job is not None
    assert new_job.job_type == "SCAN"


def test_retry_job_not_found(client):
    """Tests retrying a non-existent job returns 404."""
    response = client.post("/system/jobs/99999/retry")
    assert response.status_code == 404


def test_retry_job_not_failed(client, db_session):
    """Tests retrying a non-failed job returns 400."""
    job = models.Job(job_type="SCAN", status="COMPLETED")
    db_session.add(job)
    db_session.commit()

    response = client.post(f"/system/jobs/{job.id}/retry")
    assert response.status_code == 400
    assert "Only failed jobs can be retried" in response.json()["detail"]


def test_retry_non_scan_job(client, db_session):
    """Tests retrying a failed BACKUP job returns 400."""
    job = models.Job(job_type="BACKUP", status="FAILED")
    db_session.add(job)
    db_session.commit()

    response = client.post(f"/system/jobs/{job.id}/retry")
    assert response.status_code == 400
    assert "Retry for BACKUP jobs is not supported" in response.json()["detail"]


# ── stream_jobs ──


@pytest.mark.skip(
    reason="Async infinite SSE stream cannot be tested with synchronous TestClient"
)
def test_stream_jobs_returns_sse(client):
    """Tests that the stream endpoint is registered and accessible."""
    response = client.get("/system/jobs/stream")
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")
