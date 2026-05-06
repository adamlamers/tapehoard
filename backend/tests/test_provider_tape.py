from app.providers.tape import LTOProvider


def test_lto_compression_control(mocker):
    """Verifies that LTOProvider sends the correct mt commands for compression."""

    # Mock subprocess.run and os.path.exists
    mock_run = mocker.patch("subprocess.run")
    mocker.patch("os.path.exists", return_value=True)

    # CASE 1: Compression Enabled
    provider_on = LTOProvider({"device_path": "/dev/nst0", "compression": True})
    provider_on._setup_compression()

    # Expectation: mt compression 1
    mock_run.assert_called_with(
        ["mt", "-f", "/dev/nst0", "compression", "1"], check=True, capture_output=True
    )

    # CASE 2: Compression Disabled
    mock_run.reset_mock()
    provider_off = LTOProvider({"device_path": "/dev/nst0", "compression": False})
    provider_off._setup_compression()

    # Expectation: mt compression 0
    mock_run.assert_called_with(
        ["mt", "-f", "/dev/nst0", "compression", "0"], check=True, capture_output=True
    )


def test_lto_insertion_detection(mocker):
    """Verifies that needs_registration triggers only on new insertion."""

    device = "/dev/nst0"
    # 1. Start with Empty State
    LTOProvider._lkg_state = {
        device: {"drive": {}, "mam": {}, "online": False, "last_check": 0.0}
    }
    provider = LTOProvider({"device_path": device})

    # Mock OS path existence
    mocker.patch("os.path.exists", return_value=True)

    # Mock subprocess.run to return "READY" for status and valid MAM attributes
    def mock_subprocess(cmd, **kwargs):
        m = mocker.MagicMock()
        m.returncode = 0
        if "status" in cmd:
            m.stdout = "READY"
        elif "sg_read_attr" in cmd:
            # Mock raw MAM data bytes (minimal valid structure)
            # barcode "TAPE01" is at the end of the mapping usually
            # But we patch get_mam_info to be easier
            pass
        return m

    mocker.patch("subprocess.run", side_effect=mock_subprocess)

    # We patch get_mam_info because parsing raw bytes in a test is overkill
    mocker.patch.object(provider, "get_mam_info", return_value={"barcode": "TAPE01"})
    mocker.patch.object(provider, "get_drive_info", return_value={"vendor": "HP"})

    # Execution: First poll after "insertion" (transition from offline LKG to online)
    info = provider.get_live_info(force=True)

    # EXPECTATION: needs_registration should be True
    assert info["online"] is True
    assert info["identity"] == "TAPE01"
    assert info["needs_registration"] is True

    # 2. Second poll (already online)
    # LKG state is now updated by the provider during the first poll
    info_second = provider.get_live_info(force=True)

    # EXPECTATION: needs_registration should be False (already saw this tape)
    assert info_second["needs_registration"] is False


def test_lto_mam_parsing_logic(mocker):
    """Verifies the parsing of raw SCSI attribute bytes into human-readable metadata."""
    import struct

    device = "/dev/nst0"
    provider = LTOProvider({"device_path": device})
    mocker.patch("os.path.exists", return_value=True)

    # 1. CONSTRUCT RAW PAYLOAD
    # SCSI MAM raw format: [TotalLen(4)] + { [ID(2)][Flags(1)][Len(2)][Value] }...

    def pack_attr(attr_id, value_bytes):
        return struct.pack(">HBH", attr_id, 0, len(value_bytes)) + value_bytes

    # Remaining Capacity (0x0000): 500GB (512000 MiB)
    attr_rem = pack_attr(0x0000, (512000).to_bytes(8, "big"))
    # Max Capacity (0x0001): 1.5TB (1536000 MiB - LTO-5 raw)
    attr_max = pack_attr(0x0001, (1536000).to_bytes(8, "big"))
    # Tape Alert Flags (0x0002): Bit 20 is "Clean Now"
    # Bit 20 from left (64-bit int) -> (1 << (64-20))
    alert_flags = 1 << (64 - 20)
    attr_alerts = pack_attr(0x0002, alert_flags.to_bytes(8, "big"))
    # Barcode (0x0806): "TAPE123"
    attr_barcode = pack_attr(0x0806, b"TAPE123\x00\x00")  # null padded

    payload_body = attr_rem + attr_max + attr_alerts + attr_barcode
    full_payload = struct.pack(">I", len(payload_body)) + payload_body

    # 2. MOCK SUBPROCESS
    mock_res = mocker.MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = full_payload
    mocker.patch("subprocess.run", return_value=mock_res)

    # 3. EXECUTION
    mam = provider.get_mam_info(force=True)

    # 4. EXPECTATIONS
    assert mam["remaining_capacity_mib"] == 512000
    assert mam["max_capacity_mib"] == 1536000
    assert mam["barcode"] == "TAPE123"
    assert "Clean Now" in mam["alerts"]
    # 1.5TB should be identified as LTO-5
    assert mam["generation_label"] == "LTO-5"


def test_lto_write_archive_writes_file_mark(mocker):
    """Verifies that write_archive writes a file mark after each archive."""
    device = "/dev/nst0"
    provider = LTOProvider({"device_path": device})
    mocker.patch("os.path.exists", return_value=True)

    mt_calls = []

    def capture_mt(cmd, **kwargs):
        m = mocker.MagicMock()
        m.returncode = 0
        if "status" in cmd:
            # First call: at file 1; second call: at file 2
            m.stdout = f"File number={len(mt_calls) + 1}"
        elif "weof" in cmd:
            mt_calls.append("weof")
        return m

    mocker.patch("subprocess.run", side_effect=capture_mt)
    mocker.patch("subprocess.Popen")

    import io

    provider.write_archive("TAPE01", io.BytesIO(b"archive data"))

    # Expectation: weof must be called after dd to delimit the archive
    assert "weof" in mt_calls


def test_lto_initialize_media_writes_single_file_mark(mocker):
    """Verifies initialize_media writes exactly one file mark (after the label)."""
    device = "/dev/nst0"
    provider = LTOProvider({"device_path": device})
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch.object(provider, "is_write_protected", return_value=False)

    weof_count = 0

    def capture_mt(cmd, **kwargs):
        nonlocal weof_count
        m = mocker.MagicMock()
        m.returncode = 0
        if "weof" in cmd:
            weof_count += 1
        return m

    mocker.patch("subprocess.run", side_effect=capture_mt)

    # Popen for dd must have stdin and communicate() returning a valid tuple
    mock_proc = mocker.MagicMock()
    mock_proc.communicate.return_value = (b"", b"")
    mock_proc.returncode = 0
    mocker.patch("subprocess.Popen", return_value=mock_proc)

    provider.initialize_media("TAPE01")

    # Expectation: exactly one weof (after the label), not before
    assert weof_count == 1


def test_lto_multiple_archives_increment_file_number(mocker):
    """Verifies that writing multiple archives creates distinct tape files."""
    device = "/dev/nst0"
    provider = LTOProvider({"device_path": device})
    mocker.patch("os.path.exists", return_value=True)

    file_number = 1

    def capture_mt(cmd, **kwargs):
        nonlocal file_number
        m = mocker.MagicMock()
        m.returncode = 0
        if "status" in cmd:
            m.stdout = f"File number={file_number}"
        elif "weof" in cmd:
            file_number += 1
        return m

    mocker.patch("subprocess.run", side_effect=capture_mt)
    mocker.patch("subprocess.Popen")

    import io

    loc1 = provider.write_archive("TAPE01", io.BytesIO(b"archive1"))
    loc2 = provider.write_archive("TAPE01", io.BytesIO(b"archive2"))
    loc3 = provider.write_archive("TAPE01", io.BytesIO(b"archive3"))

    # Expectation: each archive gets a unique, incrementing file number
    assert loc1 == "1"
    assert loc2 == "2"
    assert loc3 == "3"
