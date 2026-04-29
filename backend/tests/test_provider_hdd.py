import io
import pytest
from app.providers.hdd import OfflineHDDProvider


def test_hdd_initialization(tmp_path):
    """Verifies that HDD provider correctly prepares the disk structure."""
    mount = tmp_path / "mnt_hdd"
    provider = OfflineHDDProvider({"mount_path": str(mount)})

    success = provider.initialize_media("DISK01")
    assert success is True
    assert (mount / ".tapehoard_id").exists()
    assert (mount / ".tapehoard_id").read_text().strip() == "DISK01"
    assert (mount / "tapehoard_backups" / "archives").is_dir()


def test_hdd_identification(tmp_path):
    """Verifies that HDD provider can identify a disk by its ID file."""
    mount = tmp_path / "mnt_hdd"
    mount.mkdir()
    (mount / ".tapehoard_id").write_text("DISK02")

    provider = OfflineHDDProvider({"mount_path": str(mount)})
    assert provider.identify_media() == "DISK02"


def test_hdd_write_sequential_logic(tmp_path):
    """Verifies that archives are numbered and padded correctly."""
    mount = tmp_path / "mnt_hdd"
    provider = OfflineHDDProvider({"mount_path": str(mount)})
    provider.initialize_media("DISK03")

    # Write first archive
    loc1 = provider.write_archive("DISK03", io.BytesIO(b"archive1"))
    assert loc1 == "0"
    assert (mount / "tapehoard_backups" / "archives" / "000000.tar").exists()

    # Write second archive
    loc2 = provider.write_archive("DISK03", io.BytesIO(b"archive2"))
    assert loc2 == "1"
    assert (mount / "tapehoard_backups" / "archives" / "000001.tar").exists()

    # Read them back
    with provider.read_archive("DISK03", "0") as f:
        assert f.read() == b"archive1"
    with provider.read_archive("DISK03", "1") as f:
        assert f.read() == b"archive2"


def test_hdd_direct_write_and_traversal_guard(tmp_path):
    """Verifies direct file copies and security guards."""
    mount = tmp_path / "mnt_hdd"
    provider = OfflineHDDProvider({"mount_path": str(mount)})

    # Valid direct write
    rel_path = "photos/holiday.jpg"
    loc = provider.write_file_direct("DISK04", rel_path, io.BytesIO(b"imagedata"))
    assert loc == rel_path

    target = mount / "tapehoard_backups" / "objects" / rel_path
    assert target.exists()
    assert target.read_bytes() == b"imagedata"

    # Read back (Format Negotiation)
    with provider.read_archive("DISK04", rel_path) as f:
        assert f.read() == b"imagedata"

    # Traversal Attempt
    with pytest.raises(ValueError, match="Invalid relative path"):
        provider.write_file_direct(
            "DISK04", "escape/../../secret.txt", io.BytesIO(b"bad")
        )


def test_hdd_online_check_with_uuid(tmp_path, mocker):
    """Verifies that online check validates both path and UUID."""
    mount = tmp_path / "mnt_hdd"
    mount.mkdir()

    # Mock UUID utility
    mock_get_uuid = mocker.patch("app.core.utils.get_path_uuid")
    mock_get_uuid.return_value = "UUID-123"

    # CASE 1: Correct UUID
    provider_ok = OfflineHDDProvider(
        {"mount_path": str(mount), "device_uuid": "UUID-123"}
    )
    assert provider_ok.check_online() is True

    # CASE 2: Mismatched UUID
    provider_fail = OfflineHDDProvider(
        {"mount_path": str(mount), "device_uuid": "UUID-999"}
    )
    assert provider_fail.check_online() is False

    # CASE 3: No UUID (Path only)
    provider_path_only = OfflineHDDProvider({"mount_path": str(mount)})
    assert provider_path_only.check_online() is True
