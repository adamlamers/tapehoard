from app.core.utils import get_path_uuid


def test_get_path_uuid_macos(mocker):
    """Verifies UUID extraction from diskutil on macOS."""
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("sys.platform", "darwin")

    mock_run = mocker.patch("subprocess.run")
    mock_res = mocker.MagicMock()
    mock_res.stdout = """
   Device Identifier:        disk4s1
   Device Node:              /dev/disk4s1
   Volume Name:              MyBackups
   Volume UUID:              ABCDEF-1234-5678-90AB-CDEF12345678
    """
    mock_run.return_value = mock_res

    uuid = get_path_uuid("/Volumes/MyBackups")
    assert uuid == "ABCDEF-1234-5678-90AB-CDEF12345678"
    mock_run.assert_called_with(
        ["diskutil", "info", "/Volumes/MyBackups"], capture_output=True, text=True
    )


def test_get_path_uuid_linux(mocker):
    """Verifies UUID extraction from lsblk on Linux."""
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("sys.platform", "linux")

    mock_run = mocker.patch("subprocess.run")

    def mock_subprocess(cmd, **kwargs):
        m = mocker.MagicMock()
        if "df" in cmd:
            m.stdout = "Filesystem\n/dev/sdb1"
        elif "lsblk" in cmd:
            m.stdout = "98765432-ABCD-EF01-2345-6789ABCDEF01"
        return m

    mock_run.side_effect = mock_subprocess

    uuid = get_path_uuid("/mnt/hdd")
    assert uuid == "98765432-ABCD-EF01-2345-6789ABCDEF01"
