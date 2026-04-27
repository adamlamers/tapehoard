from app.db import models
from datetime import datetime, timezone


def test_get_dashboard_stats_empty(client):
    """Tests the dashboard stats endpoint when the database is empty."""
    response = client.get("/system/dashboard/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_files_indexed"] == 0
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
        is_indexed=True,
    )
    db_session.add(file_state)
    db_session.commit()

    response = client.get("/system/dashboard/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["total_files_indexed"] == 1
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
