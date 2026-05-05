from app.services.scheduler import SchedulerService
from app.db import models


def test_scheduler_start_stop():
    """Tests scheduler lifecycle (start, stop, idempotent)."""
    scheduler = SchedulerService()
    assert not scheduler.scheduler.running

    scheduler.start()
    assert scheduler.scheduler.running

    # Idempotent start
    scheduler.start()
    assert scheduler.scheduler.running

    scheduler.stop()
    assert not scheduler.scheduler.running

    # Idempotent stop
    scheduler.stop()
    assert not scheduler.scheduler.running


def test_scheduler_load_schedules_empty():
    """Tests load_schedules with no cron settings configured."""
    scheduler = SchedulerService()
    scheduler.start()

    scheduler.load_schedules()

    # No jobs should be registered
    assert scheduler.scheduler.get_job("system_scan") is None
    assert scheduler.scheduler.get_job("system_archival") is None

    scheduler.stop()


def test_scheduler_load_schedules_with_scan(db_session):
    """Tests load_schedules picks up a scan schedule from settings."""
    db_session.add(models.SystemSetting(key="schedule_scan", value="0 2 * * *"))
    db_session.commit()

    scheduler = SchedulerService()
    scheduler.start()

    scheduler.load_schedules()

    job = scheduler.scheduler.get_job("system_scan")
    assert job is not None
    assert job.id == "system_scan"

    scheduler.stop()


def test_scheduler_add_remove_job():
    """Tests adding and removing scheduled jobs."""
    scheduler = SchedulerService()
    scheduler.start()

    def dummy_job():
        pass

    scheduler.add_job("test_job", dummy_job, "0 0 * * *")
    assert scheduler.scheduler.get_job("test_job") is not None

    scheduler.remove_job("test_job")
    assert scheduler.scheduler.get_job("test_job") is None

    # Idempotent remove
    scheduler.remove_job("test_job")
    assert scheduler.scheduler.get_job("test_job") is None

    scheduler.stop()


def test_scheduler_add_job_empty_cron():
    """Tests that empty/whitespace cron expression removes the job."""
    scheduler = SchedulerService()
    scheduler.start()

    def dummy_job():
        pass

    scheduler.add_job("test_job", dummy_job, "0 0 * * *")
    assert scheduler.scheduler.get_job("test_job") is not None

    # Empty string should remove
    scheduler.add_job("test_job", dummy_job, "  ")
    assert scheduler.scheduler.get_job("test_job") is None

    scheduler.stop()


def test_scheduler_reload(db_session, mocker):
    """Tests reload calls load_schedules."""
    db_session.add(models.SystemSetting(key="schedule_scan", value="0 3 * * *"))
    db_session.commit()

    scheduler = SchedulerService()
    scheduler.start()

    load_spy = mocker.spy(scheduler, "load_schedules")
    scheduler.reload()

    load_spy.assert_called_once()

    job = scheduler.scheduler.get_job("system_scan")
    assert job is not None

    scheduler.stop()


def test_scheduler_run_system_scan_skips_when_running(mocker):
    """Tests run_system_scan is skipped when scanner_manager is already running."""
    scheduler = SchedulerService()

    mocker.patch("app.services.scheduler.scanner_manager.is_running", True)
    scan_sources_spy = mocker.patch(
        "app.services.scheduler.scanner_manager.scan_sources"
    )

    scheduler.run_system_scan()
    scan_sources_spy.assert_not_called()


def test_scheduler_run_system_archival_no_online_media(db_session, mocker):
    """Tests run_system_archival skips when no active media is online."""
    scheduler = SchedulerService()

    # No media in DB
    run_backup_spy = mocker.patch("app.services.scheduler.archiver_manager.run_backup")

    scheduler.run_system_archival()
    run_backup_spy.assert_not_called()
