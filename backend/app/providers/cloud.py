import boto3
import io
from typing import Optional, BinaryIO, Dict, Any
from .base import AbstractStorageProvider
from .encryption import get_secret, encrypt, decrypt, obfuscated_name
from loguru import logger


class CloudStorageProvider(AbstractStorageProvider):
    provider_id = "s3_compat"
    name = "S3-Compatible Cloud Storage"
    description = "Object storage via the S3 protocol (AWS, Wasabi, Backblaze, etc)."
    capabilities = {
        "supports_random_access": True,
        "is_offline_capable": False,
        "supports_hardware_encryption": True,
    }
    config_schema = {
        "provider_template": {
            "type": "string",
            "title": "Provider Template",
            "description": "AWS S3, MinIO, Wasabi, Backblaze B2, DigitalOcean Spaces, Custom.",
            "enum": ["aws", "minio", "wasabi", "backblaze", "digitalocean", "custom"],
        },
        "endpoint_url": {
            "type": "string",
            "title": "Endpoint URL",
            "description": "e.g., https://s3.us-west-004.backblazeb2.com",
        },
        "region": {
            "type": "string",
            "title": "Region",
            "description": "Optional region",
        },
        "bucket_name": {
            "type": "string",
            "title": "Bucket Name",
        },
        "access_key_id": {
            "type": "string",
            "title": "Access Key ID",
        },
        "secret_access_key_name": {
            "type": "string",
            "title": "Secret Access Key",
            "description": "Name of a secret stored in the settings keystore.",
        },
        "path_style_access": {
            "type": "boolean",
            "title": "Path-Style Access",
            "description": "Required for MinIO and some self-hosted S3.",
            "default": False,
        },
        "storage_class": {
            "type": "string",
            "title": "Storage Class",
            "description": "Standard, Glacier, Glacier Deep Archive, etc.",
        },
        "max_part_size_mb": {
            "type": "integer",
            "title": "Max Part Size (MB)",
            "description": "Multipart upload chunk size.",
            "default": 5000,
        },
        "encryption_secret_name": {
            "type": "string",
            "title": "Encryption Secret",
            "description": "Name of a secret in the settings keystore used for client-side encryption.",
        },
        "obfuscate_filenames": {
            "type": "boolean",
            "title": "Obfuscate Filenames",
            "description": "Store files as SHA-256 hashes in the cloud to hide metadata.",
            "default": False,
        },
    }

    def __init__(self, config: Dict[str, Any]):
        self.provider_type = config.get("provider", "S3")
        self.bucket_name = config.get("bucket_name")
        self.region = config.get("region", "us-east-1")
        endpoint = config.get("endpoint_url", "")
        # Normalize endpoint: add https:// if no protocol is present
        if endpoint and not endpoint.startswith(("http://", "https://")):
            endpoint = f"https://{endpoint}"
        self.endpoint_url = endpoint or None
        self.obfuscate = config.get("obfuscate_filenames", False)

        # Resolve encryption passphrase from keystore (no global fallback)
        self.passphrase = get_secret(config.get("encryption_secret_name"))

        # Resolve credentials from keystore
        access_key = config.get("access_key")
        secret_key_name = config.get("secret_access_key_name")
        secret_key = (
            get_secret(secret_key_name) if secret_key_name else config.get("secret_key")
        )

        client_kwargs = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "region_name": self.region,
        }
        if self.endpoint_url:
            client_kwargs["endpoint_url"] = self.endpoint_url

        self.s3 = boto3.client("s3", **client_kwargs)

    def _get_obfuscated_key(self, prefix: str, path: str) -> str:
        if not self.obfuscate:
            return f"{prefix}/{path.lstrip('./')}"
        return f"{prefix}/{obfuscated_name(path)}"

    def get_name(self) -> str:
        return f"Cloud ({self.provider_type})"

    def check_online(self, force: bool = False) -> bool:
        try:
            self.s3.head_bucket(Bucket=self.bucket_name)
            return True
        except Exception:
            return False

    def get_live_info(self, force: bool = False) -> Dict[str, Any]:
        return {
            "online": self.check_online(force=force),
            "provider": self.provider_type,
            "bucket": self.bucket_name,
        }

    def check_existing_data(self) -> bool:
        try:
            response = self.s3.list_objects_v2(
                Bucket=self.bucket_name, Prefix="archives/", MaxKeys=1
            )
            return "Contents" in response
        except Exception:
            return False

    def identify_media(self, allow_intrusive=True) -> Optional[str]:
        try:
            response = self.s3.get_object(Bucket=self.bucket_name, Key=".tapehoard_id")
            return response["Body"].read().decode("utf-8").strip()
        except Exception:
            try:
                self.s3.head_bucket(Bucket=self.bucket_name)
                return self.bucket_name
            except Exception as e:
                logger.error(f"Failed to identify cloud bucket {self.bucket_name}: {e}")
                return None

    def initialize_media(self, media_id: str) -> bool:
        try:
            self.s3.head_bucket(Bucket=self.bucket_name)
            paginator = self.s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket_name):
                if "Contents" in page:
                    objects = [{"Key": obj["Key"]} for obj in page["Contents"]]
                    self.s3.delete_objects(
                        Bucket=self.bucket_name, Delete={"Objects": objects}
                    )
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=".tapehoard_id",
                Body=media_id.encode("utf-8"),
            )
            return True
        except Exception as e:
            logger.error(f"Cloud Provider: Failed to initialize media: {e}")
            return False

    def prepare_for_write(self, media_id: str) -> bool:
        return self.identify_media() == media_id

    def write_archive(self, media_id: str, stream: BinaryIO) -> str:
        import uuid

        raw_key = f"archives/{uuid.uuid4().hex}.tar"
        object_key = self._get_obfuscated_key("archives", raw_key)
        data = stream.read()

        if self.passphrase:
            logger.info(
                f"Uploading AES-256-GCM archive to {self.bucket_name}/{object_key}"
            )
            payload = encrypt(self.passphrase, data)
            try:
                self.s3.put_object(
                    Bucket=self.bucket_name,
                    Key=object_key,
                    Body=payload,
                    Metadata={"x-amz-meta-tapehoard-encrypted": "v2-gcm"},
                )
                return object_key
            except Exception as e:
                logger.error(f"GCM cloud upload failed: {e}")
                raise
        else:
            logger.info(f"Uploading plain archive to {self.bucket_name}/{object_key}")
            try:
                self.s3.upload_fileobj(io.BytesIO(data), self.bucket_name, object_key)
                return object_key
            except Exception as e:
                logger.error(f"Cloud upload failed: {e}")
                raise

    def write_file_direct(
        self, media_id: str, relative_path: str, stream: BinaryIO
    ) -> str:
        object_key = self._get_obfuscated_key("objects", relative_path)
        data = stream.read()

        if self.passphrase:
            logger.info(
                f"Uploading AES-256-GCM object to {self.bucket_name}/{object_key}"
            )
            payload = encrypt(self.passphrase, data)
            try:
                self.s3.put_object(
                    Bucket=self.bucket_name,
                    Key=object_key,
                    Body=payload,
                    Metadata={"x-amz-meta-tapehoard-encrypted": "v2-gcm"},
                )
                return object_key
            except Exception as e:
                logger.error(f"GCM cloud object upload failed: {e}")
                raise
        else:
            logger.info(f"Uploading plain object to {self.bucket_name}/{object_key}")
            try:
                self.s3.upload_fileobj(io.BytesIO(data), self.bucket_name, object_key)
                return object_key
            except Exception as e:
                logger.error(f"Cloud object upload failed: {e}")
                raise

    def read_archive(self, media_id: str, location_id: str) -> BinaryIO:
        response = self.s3.get_object(Bucket=self.bucket_name, Key=location_id)
        raw_payload = response["Body"].read()

        metadata = response.get("Metadata", {})
        is_encrypted = (
            metadata.get("tapehoard-encrypted") == "v2-gcm"
            or metadata.get("x-amz-meta-tapehoard-encrypted") == "v2-gcm"
        )

        if is_encrypted:
            logger.info(f"Decrypting AES-GCM cloud archive: {location_id}")
            try:
                return io.BytesIO(decrypt(self.passphrase, raw_payload))
            except ValueError as e:
                logger.error(f"Decryption failed (MAC mismatch): {e}")
                raise ValueError(
                    "Cloud archive tampering detected or incorrect passphrase!"
                )

        return io.BytesIO(raw_payload)

    def finalize_media(self, media_id: str):
        logger.info(f"Finalized cloud media {media_id}")
