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
