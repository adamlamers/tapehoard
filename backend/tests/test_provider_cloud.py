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


def test_cloud_secret_lookup(mocker, db_session):
    """Verifies that the provider looks up secrets from the keystore by name."""
    from app.db import models

    # Mock boto3.client to avoid slow initialization in unit tests
    mocker.patch("app.providers.cloud.boto3")

    # Seed the secrets keystore
    db_session.add(
        models.SystemSetting(
            key="secrets",
            value='{"my-encryption-key": "local-override", "empty-secret": ""}',
        )
    )
    db_session.commit()

    # CASE 1: Secret name provided and exists in keystore
    config_local = {
        "bucket_name": "b",
        "encryption_secret_name": "my-encryption-key",
    }
    provider_local = CloudStorageProvider(config_local)
    assert provider_local.passphrase == "local-override"

    # CASE 2: No secret name provided, passphrase is None
    config_empty = {"bucket_name": "b"}
    provider_fallback = CloudStorageProvider(config_empty)
    assert provider_fallback.passphrase is None

    # CASE 3: Secret name provided but value is empty string
    config_empty_secret = {
        "bucket_name": "b",
        "encryption_secret_name": "empty-secret",
    }
    provider_empty = CloudStorageProvider(config_empty_secret)
    assert provider_empty.passphrase == ""

    # CASE 4: No passphrase anywhere (ValueError on key derivation)
    provider_none = CloudStorageProvider({"bucket_name": "b"})
    with pytest.raises(ValueError, match="No encryption passphrase configured"):
        provider_none._derive_key(b"salt")
