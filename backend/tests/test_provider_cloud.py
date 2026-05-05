import io
import os
import pytest
from unittest.mock import MagicMock

from app.providers.cloud import CloudStorageProvider


# ── Constructor & Config ──


def test_cloud_provider_endpoint_normalization(mocker):
    """Tests that endpoint URLs without protocol get https:// prepended."""
    mock_boto = mocker.patch("app.providers.cloud.boto3")

    provider = CloudStorageProvider(
        {
            "bucket_name": "test-bucket",
            "endpoint_url": "s3.example.com",
            "region": "eu-west-1",
            "access_key": "ak",
            "secret_key": "sk",
        }
    )

    call_kwargs = mock_boto.client.call_args[1]
    assert call_kwargs["endpoint_url"] == "https://s3.example.com"
    assert call_kwargs["region_name"] == "eu-west-1"
    assert provider.provider_type == "S3"


def test_cloud_provider_endpoint_no_modification(mocker):
    """Tests that endpoint URLs with existing protocol are left alone."""
    mock_boto = mocker.patch("app.providers.cloud.boto3")

    CloudStorageProvider(
        {
            "bucket_name": "test-bucket",
            "endpoint_url": "http://minio.local:9000",
        }
    )

    call_kwargs = mock_boto.client.call_args[1]
    assert call_kwargs["endpoint_url"] == "http://minio.local:9000"


def test_cloud_provider_defaults(mocker):
    """Tests default values when minimal config is provided."""
    mock_boto = mocker.patch("app.providers.cloud.boto3")

    provider = CloudStorageProvider({"bucket_name": "b"})

    assert provider.region == "us-east-1"
    assert provider.endpoint_url is None
    assert provider.obfuscate is False
    mock_boto.client.assert_called_once()


# ── Online & Identification ──


def test_check_online_success(mocker):
    """Tests check_online returns True when head_bucket succeeds."""
    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider({"bucket_name": "b"})
    provider.s3.head_bucket = MagicMock(return_value=None)

    assert provider.check_online() is True


def test_check_online_failure(mocker):
    """Tests check_online returns False when head_bucket raises."""
    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider({"bucket_name": "b"})
    provider.s3.head_bucket = MagicMock(side_effect=Exception("timeout"))

    assert provider.check_online() is False


def test_get_live_info(mocker):
    """Tests get_live_info returns provider metadata."""
    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider({"bucket_name": "my-bucket"})
    provider.s3.head_bucket = MagicMock(return_value=None)

    info = provider.get_live_info()
    assert info["online"] is True
    assert info["provider"] == "S3"
    assert info["bucket"] == "my-bucket"


def test_check_existing_data_found(mocker):
    """Tests check_existing_data when objects exist under archives/."""
    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider({"bucket_name": "b"})
    provider.s3.list_objects_v2 = MagicMock(
        return_value={"Contents": [{"Key": "archives/1.tar"}]}
    )

    assert provider.check_existing_data() is True


def test_check_existing_data_empty(mocker):
    """Tests check_existing_data when no objects exist."""
    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider({"bucket_name": "b"})
    provider.s3.list_objects_v2 = MagicMock(return_value={})

    assert provider.check_existing_data() is False


def test_identify_media_by_id_file(mocker):
    """Tests identify_media reads .tapehoard_id when available."""
    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider({"bucket_name": "b"})
    mock_body = MagicMock()
    mock_body.read.return_value = b"  BUCKET_001  "
    provider.s3.get_object = MagicMock(return_value={"Body": mock_body})

    result = provider.identify_media()
    assert result == "BUCKET_001"


def test_identify_media_fallback_to_bucket_name(mocker):
    """Tests identify_media falls back to bucket name when .tapehoard_id missing."""
    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider({"bucket_name": "fallback-bucket"})
    provider.s3.get_object = MagicMock(side_effect=Exception("NoSuchKey"))
    provider.s3.head_bucket = MagicMock(return_value=None)

    result = provider.identify_media()
    assert result == "fallback-bucket"


def test_identify_media_complete_failure(mocker):
    """Tests identify_media returns None when everything fails."""
    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider({"bucket_name": "b"})
    provider.s3.get_object = MagicMock(side_effect=Exception("fail"))
    provider.s3.head_bucket = MagicMock(side_effect=Exception("fail"))

    assert provider.identify_media() is None


# ── Write Operations ──


def test_write_archive_plain(mocker):
    """Tests writing an unencrypted archive."""
    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider({"bucket_name": "b", "obfuscate_filenames": False})

    stream = io.BytesIO(b"archive content")
    provider.s3.upload_fileobj = MagicMock(return_value=None)

    location = provider.write_archive("M1", stream)

    assert location.startswith("archives/archives/")
    assert location.endswith(".tar")
    provider.s3.upload_fileobj.assert_called_once()


def test_write_file_direct_plain(mocker):
    """Tests writing an unencrypted object directly."""
    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider({"bucket_name": "b", "obfuscate_filenames": False})

    stream = io.BytesIO(b"file content")
    provider.s3.upload_fileobj = MagicMock(return_value=None)

    location = provider.write_file_direct("M1", "photos/image.jpg", stream)

    assert location == "objects/photos/image.jpg"


def test_initialize_media_clears_and_tags(mocker):
    """Tests initialize_media clears existing objects and writes .tapehoard_id."""
    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider({"bucket_name": "b"})

    provider.s3.head_bucket = MagicMock(return_value=None)
    mock_paginator = MagicMock()
    mock_paginator.paginate = MagicMock(
        return_value=[{"Contents": [{"Key": "old1"}, {"Key": "old2"}]}]
    )
    provider.s3.get_paginator = MagicMock(return_value=mock_paginator)
    provider.s3.delete_objects = MagicMock(return_value=None)
    provider.s3.put_object = MagicMock(return_value=None)

    result = provider.initialize_media("NEW_DISK")

    assert result is True
    provider.s3.delete_objects.assert_called_once()
    provider.s3.put_object.assert_called_once()
    call_kwargs = provider.s3.put_object.call_args[1]
    assert call_kwargs["Key"] == ".tapehoard_id"
    assert call_kwargs["Body"] == b"NEW_DISK"


def test_initialize_media_failure(mocker):
    """Tests initialize_media returns False on error."""
    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider({"bucket_name": "b"})
    provider.s3.head_bucket = MagicMock(side_effect=Exception("no access"))

    assert provider.initialize_media("X") is False


def test_prepare_for_write_match(mocker):
    """Tests prepare_for_write when media identifier matches."""
    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider({"bucket_name": "b"})
    provider.s3.head_bucket = MagicMock(return_value=None)
    provider.s3.get_object = MagicMock(side_effect=Exception("not found"))

    # Fallback to bucket name
    assert provider.prepare_for_write("b") is True
    assert provider.prepare_for_write("wrong") is False


# ── Read Operations ──


def test_read_archive_plain(mocker):
    """Tests reading an unencrypted archive."""
    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider({"bucket_name": "b"})

    provider.s3.get_object = MagicMock(
        return_value={
            "Body": io.BytesIO(b"raw archive data"),
            "Metadata": {},
        }
    )

    result = provider.read_archive("M1", "archives/1.tar")
    assert result.read() == b"raw archive data"


def test_read_archive_encrypted(mocker, db_session):
    """Tests round-trip encryption/decryption for archives."""
    from app.db import models
    from Crypto.Cipher import AES
    from Crypto.Protocol.KDF import PBKDF2
    from Crypto.Hash import SHA256

    # Seed passphrase in keystore
    db_session.add(
        models.SystemSetting(key="secrets", value='{"cloud-enc": "my-passphrase-123"}')
    )
    db_session.commit()

    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider(
        {
            "bucket_name": "b",
            "encryption_secret_name": "cloud-enc",
        }
    )

    # Encrypt data ourselves to simulate stored payload
    original_data = b"secret archive content"
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = PBKDF2(
        "my-passphrase-123", salt, dkLen=32, count=100000, hmac_hash_module=SHA256
    )
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(original_data)
    payload = salt + nonce + tag + ciphertext

    provider.s3.get_object = MagicMock(
        return_value={
            "Body": io.BytesIO(payload),
            "Metadata": {"tapehoard-encrypted": "v2-gcm"},
        }
    )

    result = provider.read_archive("M1", "archives/enc.tar")
    assert result.read() == original_data


def test_read_archive_encrypted_tampered(mocker, db_session):
    """Tests that tampered encrypted archive raises ValueError."""
    from app.db import models

    db_session.add(
        models.SystemSetting(key="secrets", value='{"cloud-enc": "my-passphrase-123"}')
    )
    db_session.commit()

    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider(
        {
            "bucket_name": "b",
            "encryption_secret_name": "cloud-enc",
        }
    )

    # Corrupt payload: valid structure but wrong ciphertext
    fake_payload = os.urandom(16) + os.urandom(12) + os.urandom(16) + b"garbage"

    provider.s3.get_object = MagicMock(
        return_value={
            "Body": io.BytesIO(fake_payload),
            "Metadata": {"tapehoard-encrypted": "v2-gcm"},
        }
    )

    with pytest.raises(ValueError, match="tampering detected"):
        provider.read_archive("M1", "archives/bad.tar")


# ── Encryption Round-Trip ──


def test_write_and_read_archive_encrypted(mocker, db_session):
    """End-to-end test: write encrypted archive, read it back."""
    from app.db import models

    db_session.add(
        models.SystemSetting(key="secrets", value='{"cloud-enc": "my-passphrase-123"}')
    )
    db_session.commit()

    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider(
        {
            "bucket_name": "b",
            "encryption_secret_name": "cloud-enc",
            "obfuscate_filenames": False,
        }
    )

    # Capture the uploaded payload
    uploaded = {}

    def capture_put_object(**kwargs):
        uploaded["key"] = kwargs["Key"]
        uploaded["body"] = kwargs["Body"]
        uploaded["metadata"] = kwargs.get("Metadata", {})

    provider.s3.put_object = MagicMock(side_effect=capture_put_object)

    original = b"round-trip test data"
    location = provider.write_archive("M1", io.BytesIO(original))

    # Verify upload happened with encryption metadata
    assert uploaded["metadata"].get("x-amz-meta-tapehoard-encrypted") == "v2-gcm"
    assert uploaded["metadata"].get("x-amz-meta-tapehoard-type") == "archive"

    # Now read it back
    provider.s3.get_object = MagicMock(
        return_value={
            "Body": io.BytesIO(uploaded["body"]),
            "Metadata": {"tapehoard-encrypted": "v2-gcm"},
        }
    )

    result = provider.read_archive("M1", location)
    assert result.read() == original


# ── Misc ──


def test_get_name(mocker):
    """Tests get_name returns provider type string."""
    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider({"bucket_name": "b", "provider": "Wasabi"})
    assert provider.get_name() == "Cloud (Wasabi)"


def test_finalize_media(mocker):
    """Tests finalize_media is a no-op that logs."""
    mocker.patch("app.providers.cloud.boto3")
    provider = CloudStorageProvider({"bucket_name": "b"})
    # Should not raise
    provider.finalize_media("M1")
