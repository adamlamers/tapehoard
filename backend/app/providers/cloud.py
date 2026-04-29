import hashlib
import boto3
import os
import io
from typing import Optional, BinaryIO, Dict, Any
from .base import AbstractStorageProvider
from loguru import logger

# Modern high-performance encryption via PyCryptodome
from Crypto.Cipher import AES
from Crypto.Protocol.KDF import PBKDF2
from Crypto.Hash import SHA256

from app.core.config import settings


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
        "endpoint_url": {
            "type": "string",
            "title": "Endpoint URL",
            "description": "e.g., https://s3.us-west-004.backblazeb2.com",
        },
        "bucket_name": {
            "type": "string",
            "title": "Bucket Name",
        },
        "region": {
            "type": "string",
            "title": "Region",
            "description": "Optional region",
        },
        "access_key": {
            "type": "string",
            "title": "Access Key ID",
        },
        "secret_key": {
            "type": "string",
            "title": "Secret Access Key",
        },
        "encryption_passphrase": {
            "type": "string",
            "title": "Client-Side Encryption Passphrase",
            "description": "Used to encrypt data locally before uploading via AES-256-GCM.",
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
        self.endpoint_url = config.get("endpoint_url")
        self.obfuscate = config.get("obfuscate_filenames", False)

        # Local Encryption Settings: Use provided or global default
        self.passphrase = (
            config.get("encryption_passphrase") or settings.encryption_passphrase
        )

        # Credentials
        access_key = config.get("access_key")
        secret_key = config.get("secret_key")

        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=self.region,
            endpoint_url=self.endpoint_url,
        )

    def _derive_key(self, salt: bytes) -> bytes:
        """Derives a 256-bit AES key using PBKDF2-HMAC-SHA256"""
        if not self.passphrase:
            raise ValueError("No encryption passphrase configured")

        return PBKDF2(
            self.passphrase, salt, dkLen=32, count=100000, hmac_hash_module=SHA256
        )

    def _get_obfuscated_key(self, prefix: str, path: str) -> str:
        """Returns a hashed version of the filename if obfuscation is enabled."""
        if not self.obfuscate:
            return f"{prefix}/{path.lstrip('./')}"

        # We hash the path to hide metadata while keeping it deterministic
        hashed = hashlib.sha256(path.encode("utf-8")).hexdigest()
        # Use two-level sharding to prevent S3 prefix performance issues with 100k+ files
        return f"{prefix}/{hashed[:2]}/{hashed[2:4]}/{hashed}"

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

    def identify_media(self) -> Optional[str]:
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
        """
        Encrypts data with AES-256-GCM before upload.
        Format: [Salt (16)] + [Nonce (12)] + [Tag (16)] + [Ciphertext]
        """
        import uuid

        # Archives are always obfuscated by UUID for privacy and collision avoidance
        raw_key = f"archives/{uuid.uuid4().hex}.tar"
        object_key = self._get_obfuscated_key("archives", raw_key)

        if self.passphrase:
            logger.info(
                f"Uploading AES-256-GCM archive to {self.bucket_name}/{object_key}"
            )

            # 1. Setup crypto artifacts
            salt = os.urandom(16)
            nonce = os.urandom(12)
            key = self._derive_key(salt)

            # 2. Encrypt
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
            data = stream.read()
            ciphertext, tag = cipher.encrypt_and_digest(data)

            # 3. Concatenate and upload
            payload = salt + nonce + tag + ciphertext

            try:
                self.s3.put_object(
                    Bucket=self.bucket_name,
                    Key=object_key,
                    Body=payload,
                    Metadata={
                        "x-amz-meta-tapehoard-encrypted": "v2-gcm",
                        "x-amz-meta-tapehoard-type": "archive",
                    },
                )
                return object_key
            except Exception as e:
                logger.error(f"GCM cloud upload failed: {e}")
                raise
        else:
            logger.info(f"Uploading plain archive to {self.bucket_name}/{object_key}")
            try:
                self.s3.upload_fileobj(stream, self.bucket_name, object_key)
                return object_key
            except Exception as e:
                logger.error(f"Cloud upload failed: {e}")
                raise

    def write_file_direct(
        self, media_id: str, relative_path: str, stream: BinaryIO
    ) -> str:
        """
        Uploads a single file directly to the cloud.
        """
        object_key = self._get_obfuscated_key("objects", relative_path)

        if self.passphrase:
            logger.info(
                f"Uploading AES-256-GCM object to {self.bucket_name}/{object_key}"
            )

            # 1. Setup crypto artifacts
            salt = os.urandom(16)
            nonce = os.urandom(12)
            key = self._derive_key(salt)

            # 2. Encrypt
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
            data = stream.read()
            ciphertext, tag = cipher.encrypt_and_digest(data)

            # 3. Concatenate and upload
            payload = salt + nonce + tag + ciphertext

            try:
                self.s3.put_object(
                    Bucket=self.bucket_name,
                    Key=object_key,
                    Body=payload,
                    Metadata={
                        "x-amz-meta-tapehoard-encrypted": "v2-gcm",
                        "x-amz-meta-tapehoard-type": "object",
                    },
                )
                return object_key
            except Exception as e:
                logger.error(f"GCM cloud object upload failed: {e}")
                raise
        else:
            logger.info(f"Uploading plain object to {self.bucket_name}/{object_key}")
            try:
                self.s3.upload_fileobj(stream, self.bucket_name, object_key)
                return object_key
            except Exception as e:
                logger.error(f"Cloud object upload failed: {e}")
                raise

    def read_archive(self, media_id: str, location_id: str) -> BinaryIO:
        """Retrieves and decrypts an AES-GCM archive"""
        response = self.s3.get_object(Bucket=self.bucket_name, Key=location_id)
        raw_payload = response["Body"].read()

        metadata = response.get("Metadata", {})
        is_encrypted = (
            metadata.get("tapehoard-encrypted") == "v2-gcm"
            or metadata.get("x-amz-meta-tapehoard-encrypted") == "v2-gcm"
        )

        if is_encrypted:
            logger.info(f"Decrypting AES-GCM cloud archive: {location_id}")

            # Extract artifacts from payload
            salt = raw_payload[:16]
            nonce = raw_payload[16:28]
            tag = raw_payload[28:44]
            ciphertext = raw_payload[44:]

            # Derive key and decrypt
            key = self._derive_key(salt)
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)

            try:
                decrypted_data = cipher.decrypt_and_verify(ciphertext, tag)
                return io.BytesIO(decrypted_data)
            except ValueError as e:
                logger.error(f"Decryption failed (MAC mismatch): {e}")
                raise ValueError(
                    "Cloud archive tampering detected or incorrect passphrase!"
                )

        return io.BytesIO(raw_payload)

    def finalize_media(self, media_id: str):
        logger.info(f"Finalized cloud media {media_id}")
