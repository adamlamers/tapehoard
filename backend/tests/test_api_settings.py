from app.db import models

# ── Settings CRUD ──


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


def test_update_settings_triggers_scheduler_reload(client, mocker):
    """Tests that updating schedule_scan reloads the scheduler."""
    from app.services.scheduler import scheduler_manager

    reload_spy = mocker.spy(scheduler_manager, "reload")
    response = client.post(
        "/system/settings", json={"key": "schedule_scan", "value": "0 3 * * *"}
    )
    assert response.status_code == 200
    reload_spy.assert_called_once()


def test_update_global_exclusions_recomputes_policy(client, db_session, mocker):
    """Tests that updating global_exclusions triggers policy recompute."""
    recompute_spy = mocker.patch("app.api.system.settings.recompute_exclusion_policy")
    response = client.post(
        "/system/settings",
        json={"key": "global_exclusions", "value": "*.tmp\n*.log"},
    )
    assert response.status_code == 200
    recompute_spy.assert_called_once()


# ── Exclusion Testing ──


def test_test_exclusions_empty_patterns(client):
    """Tests exclusion test with empty patterns returns zeros."""
    response = client.post(
        "/system/settings/test-exclusions",
        json={"patterns": "", "limit": 10},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_files"] == 0
    assert data["matched_count"] == 0
    assert data["sample"] == []


def test_test_exclusions_matches_files(client, db_session):
    """Tests exclusion patterns against indexed files."""
    db_session.add_all(
        [
            models.FilesystemState(
                file_path="/data/file.txt", size=100, mtime=1000, is_deleted=False
            ),
            models.FilesystemState(
                file_path="/data/temp.tmp", size=50, mtime=1000, is_deleted=False
            ),
            models.FilesystemState(
                file_path="/data/debug.log", size=200, mtime=1000, is_deleted=False
            ),
        ]
    )
    db_session.commit()

    response = client.post(
        "/system/settings/test-exclusions",
        json={"patterns": "*.tmp\n*.log", "limit": 10},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_files"] == 3
    assert data["matched_count"] == 2
    assert data["matched_size"] == 250
    assert len(data["sample"]) == 2


def test_test_exclusions_deleted_files_excluded(client, db_session):
    """Tests that deleted files are excluded from exclusion testing."""
    db_session.add_all(
        [
            models.FilesystemState(
                file_path="/data/keep.txt",
                size=100,
                mtime=1000,
                is_deleted=False,
            ),
            models.FilesystemState(
                file_path="/data/old.tmp",
                size=50,
                mtime=1000,
                is_deleted=True,
            ),
        ]
    )
    db_session.commit()

    response = client.post(
        "/system/settings/test-exclusions",
        json={"patterns": "*.tmp", "limit": 10},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_files"] == 1
    assert data["matched_count"] == 0


# ── Exclusion Report Download ──


def test_download_exclusion_report(client, db_session):
    """Tests CSV report generation for exclusion matches."""
    db_session.add(
        models.FilesystemState(
            file_path="/data/target.log", size=100, mtime=1000, is_deleted=False
        )
    )
    db_session.commit()

    response = client.post(
        "/system/settings/test-exclusions/download",
        json={"patterns": "*.log", "limit": 10},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert "exclusion_report.csv" in response.headers["content-disposition"]
    content = response.content.decode("utf-8")
    assert "path,size,mtime,sha256_hash" in content
    assert "target.log" in content


def test_download_exclusion_report_no_patterns(client):
    """Tests download with empty patterns returns 400."""
    response = client.post(
        "/system/settings/test-exclusions/download",
        json={"patterns": "", "limit": 10},
    )
    assert response.status_code == 400
    assert "No patterns provided" in response.json()["detail"]


# ── Secrets Keystore (complementing test_api_system.py) ──


def test_create_secret(client):
    """Tests creating a secret."""
    response = client.post(
        "/system/secrets", json={"name": "api-key", "value": "secret123"}
    )
    assert response.status_code == 200
    assert "stored" in response.json()["message"]

    response = client.get("/system/secrets")
    assert "api-key" in response.json()


def test_get_secret_value(client):
    """Tests retrieving a secret value."""
    client.post("/system/secrets", json={"name": "key-1", "value": "val-1"})

    response = client.get("/system/secrets/key-1")
    assert response.status_code == 200
    assert response.json()["value"] == "val-1"


def test_delete_secret(client):
    """Tests deleting a secret."""
    client.post("/system/secrets", json={"name": "to-delete", "value": "x"})

    response = client.request("DELETE", "/system/secrets", json={"name": "to-delete"})
    assert response.status_code == 200

    response = client.get("/system/secrets")
    assert "to-delete" not in response.json()


def test_delete_secret_not_found(client):
    """Tests deleting a non-existent secret returns 404."""
    response = client.request("DELETE", "/system/secrets", json={"name": "missing"})
    assert response.status_code == 404
