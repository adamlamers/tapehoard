import boto3
from typing import Optional, BinaryIO, Dict, Any
from .base import AbstractStorageProvider
from loguru import logger


class CloudStorageProvider(AbstractStorageProvider):
    def __init__(self, config: Dict[str, Any]):
        self.provider_type = config.get("provider", "S3")
        self.bucket_name = config.get("bucket_name")
        self.region = config.get("region", "us-east-1")
        self.endpoint_url = config.get("endpoint_url")  # For non-AWS S3 (B2, Wasabi)

        # We assume credentials are in env or handled by the host
        self.s3 = boto3.client(
            "s3", region_name=self.region, endpoint_url=self.endpoint_url
        )

    def get_name(self) -> str:
        return f"Cloud ({self.provider_type})"

    def identify_media(self) -> Optional[str]:
        """Checks if the bucket exists and we have access"""
        try:
            self.s3.head_bucket(Bucket=self.bucket_name)
            return self.bucket_name
        except Exception as e:
            logger.error(f"Failed to identify cloud bucket {self.bucket_name}: {e}")
            return None

    def initialize_media(self, media_id: str) -> bool:
        """Initializes cloud media by writing a dummy object to verify access"""
        try:
            self.s3.head_bucket(Bucket=self.bucket_name)
            self.s3.put_object(
                Bucket=self.bucket_name,
                Key=".tapehoard_id",
                Body=media_id.encode("utf-8"),
            )
            logger.info(f"Initialized Cloud bucket {media_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize cloud bucket {self.bucket_name}: {e}")
            return False

    def prepare_for_write(self, media_id: str) -> bool:
        return self.identify_media() == media_id

    def write_archive(self, media_id: str, stream: BinaryIO) -> str:
        """Uploads the stream as a new object in the bucket"""
        # Generate a unique object key (future: use job timestamp)
        import uuid

        object_key = f"archives/{uuid.uuid4().hex}.tar"

        logger.info(f"Uploading archive to cloud: {media_id}/{object_key}")
        try:
            self.s3.upload_fileobj(stream, self.bucket_name, object_key)
            return object_key
        except Exception as e:
            logger.error(f"Cloud upload failed: {e}")
            raise

    def finalize_media(self, media_id: str):
        logger.info(f"Finalized cloud media {media_id}")

    def read_archive(self, media_id: str, location_id: str) -> BinaryIO:
        """Returns a streaming body for the S3 object"""
        response = self.s3.get_object(Bucket=self.bucket_name, Key=location_id)
        return response["Body"]
