import hashlib
import pytest
from app.providers.cloud import CloudStorageProvider


def test_cloud_provider_obfuscation_logic():
    """Verifies that filename hashing and sharding works as expected."""

    # CASE 1: Obfuscation Disabled
    config_plain = {
        "bucket_name": "test-bucket",
        "obfuscate_filenames": False,
        "access_key": "fake",
        "secret_key": "fake",
    }
    provider_plain = CloudStorageProvider(config_plain)
    path = "documents/secret_plan.pdf"

    # Expectation: Key is exactly the path with prefix
    key_plain = provider_plain._get_obfuscated_key("objects", path)
    assert key_plain == "objects/documents/secret_plan.pdf"

    # CASE 2: Obfuscation Enabled
    config_hidden = {
        "bucket_name": "test-bucket",
        "obfuscate_filenames": True,
        "access_key": "fake",
        "secret_key": "fake",
    }
    provider_hidden = CloudStorageProvider(config_hidden)

    # Expectation: Key is hashed and sharded
    # hash of "documents/secret_plan.pdf"
    expected_hash = hashlib.sha256(path.encode("utf-8")).hexdigest()
    expected_prefix = f"objects/{expected_hash[:2]}/{expected_hash[2:4]}"

    key_hidden = provider_hidden._get_obfuscated_key("objects", path)

    assert key_hidden.startswith("objects/")
    assert key_hidden == f"{expected_prefix}/{expected_hash}"
    assert "secret_plan.pdf" not in key_hidden


def test_cloud_secret_fallback(mocker):
    """Verifies that the provider prioritizes local config over global settings for passphrases."""
    from app.core.config import settings

    # Mock boto3.client to avoid slow initialization in unit tests
    mocker.patch("app.providers.cloud.boto3")

    # Mock global settings
    mocker.patch.object(settings, "encryption_passphrase", "global-fallback")

    # CASE1: Local config provides passphrase
    config_local = {"bucket_name": "b", "encryption_passphrase": "local-override"}
    provider_local = CloudStorageProvider(config_local)
    assert provider_local.passphrase == "local-override"

    # CASE 2: Local config is empty, should fallback to global
    config_empty = {"bucket_name": "b"}
    provider_fallback = CloudStorageProvider(config_empty)
    assert provider_fallback.passphrase == "global-fallback"

    # CASE 3: No passphrase anywhere (ValueError on key derivation)
    mocker.patch.object(settings, "encryption_passphrase", "")
    provider_none = CloudStorageProvider({"bucket_name": "b"})
    with pytest.raises(ValueError, match="No encryption passphrase configured"):
        provider_none._derive_key(b"salt")
