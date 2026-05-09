import io
import json
import uuid
from typing import Any, BinaryIO, Dict, Optional

from loguru import logger

from .base import AbstractStorageProvider
from .encryption import decrypt, encrypt, get_secret, obfuscated_name

_CHUNK_SIZE = 5 * 1024 * 1024  # 5 MB resumable-upload chunk


def _load_setting(key: str) -> Optional[str]:
    try:
        from app.db import models
        from app.db.database import SessionLocal

        with SessionLocal() as db:
            r = (
                db.query(models.SystemSetting)
                .filter(models.SystemSetting.key == key)
                .first()
            )
            return r.value if r else None
    except Exception:
        return None


def _save_setting(key: str, value: str) -> None:
    try:
        from app.db import models
        from app.db.database import SessionLocal

        with SessionLocal() as db:
            r = (
                db.query(models.SystemSetting)
                .filter(models.SystemSetting.key == key)
                .first()
            )
            if r:
                r.value = value
            else:
                db.add(models.SystemSetting(key=key, value=value))
            db.commit()
    except Exception as e:
        logger.error(f"Failed to save setting {key}: {e}")


class GoogleDriveProvider(AbstractStorageProvider):
    provider_id = "google_drive"
    name = "Google Drive"
    description = "Store archives in a Google Drive folder via OAuth2."
    capabilities = {
        "supports_random_access": True,
        "is_offline_capable": False,
        "supports_hardware_encryption": False,
    }
    config_schema = {
        "credential_key": {
            "type": "string",
            "title": "OAuth Credential Key",
            "description": "Internal reference key for stored OAuth tokens. Set via 'Connect with Google'.",
        },
        "folder_id": {
            "type": "string",
            "title": "Drive Folder ID",
            "description": "Google Drive folder ID for this media. Auto-set after Initialize Media.",
        },
    }

    def __init__(self, config: Dict[str, Any]):
        self.credential_key: Optional[str] = config.get("credential_key")
        self.folder_id: Optional[str] = config.get("folder_id")
        self._service = None
        self.passphrase = get_secret(config.get("encryption_secret_name"))
        self.obfuscate: bool = bool(config.get("obfuscate_filenames", False))

    # --- Helpers ---

    def _get_credentials(self):
        if not self.credential_key:
            raise ValueError(
                "No OAuth credential configured for this Google Drive media."
            )

        cred_json = _load_setting(self.credential_key)
        if not cred_json:
            raise ValueError(f"OAuth credential '{self.credential_key}' not found.")

        cred_data = json.loads(cred_json)
        client_id = get_secret("google_drive_client_id")
        client_secret = get_secret("google_drive_client_secret")

        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        creds = Credentials(
            token=cred_data.get("access_token"),
            refresh_token=cred_data.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=cred_data.get("scopes"),
        )

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            cred_data["access_token"] = creds.token
            _save_setting(self.credential_key, json.dumps(cred_data))

        return creds

    def _get_service(self):
        if self._service is None:
            from googleapiclient.discovery import build

            creds = self._get_credentials()
            self._service = build(
                "drive", "v3", credentials=creds, cache_discovery=False
            )
        return self._service

    def _archive_filename(self, raw_name: str) -> str:
        return obfuscated_name(raw_name) if self.obfuscate else raw_name

    def _find_file(self, name: str, parent_id: str) -> Optional[str]:
        result = (
            self._get_service()
            .files()
            .list(
                q=f"name='{name}' and '{parent_id}' in parents and trashed=false",
                pageSize=1,
                fields="files(id)",
            )
            .execute()
        )
        files = result.get("files", [])
        return files[0]["id"] if files else None

    # --- AbstractStorageProvider implementation ---

    def get_name(self) -> str:
        return "Google Drive"

    def check_online(self, force: bool = False) -> bool:
        try:
            self._get_service().about().get(fields="user").execute()
            return True
        except Exception:
            return False

    def check_existing_data(self) -> bool:
        if not self.folder_id:
            return False
        try:
            result = (
                self._get_service()
                .files()
                .list(
                    q=f"'{self.folder_id}' in parents and trashed=false",
                    pageSize=1,
                    fields="files(id)",
                )
                .execute()
            )
            return len(result.get("files", [])) > 0
        except Exception:
            return False

    def identify_media(self, allow_intrusive=True) -> Optional[str]:
        if not self.folder_id:
            return None
        try:
            file_id = self._find_file(".tapehoard_id", self.folder_id)
            if not file_id:
                return None
            content = self._get_service().files().get_media(fileId=file_id).execute()
            return content.decode("utf-8").strip()
        except Exception as e:
            logger.error(f"GoogleDrive identify_media failed: {e}")
            return None

    def initialize_media(self, media_id: str) -> bool:
        try:
            service = self._get_service()

            # Find or create top-level TapeHoard folder
            th_result = (
                service.files()
                .list(
                    q="name='TapeHoard' and mimeType='application/vnd.google-apps.folder' and 'root' in parents and trashed=false",
                    pageSize=1,
                    fields="files(id)",
                )
                .execute()
            )
            if th_result.get("files"):
                th_id = th_result["files"][0]["id"]
            else:
                th_id = (
                    service.files()
                    .create(
                        body={
                            "name": "TapeHoard",
                            "mimeType": "application/vnd.google-apps.folder",
                        },
                        fields="id",
                    )
                    .execute()["id"]
                )

            # Create per-media folder
            folder = (
                service.files()
                .create(
                    body={
                        "name": media_id,
                        "mimeType": "application/vnd.google-apps.folder",
                        "parents": [th_id],
                    },
                    fields="id",
                )
                .execute()
            )
            self.folder_id = folder["id"]

            # Write identity marker
            from googleapiclient.http import MediaIoBaseUpload

            service.files().create(
                body={"name": ".tapehoard_id", "parents": [self.folder_id]},
                media_body=MediaIoBaseUpload(
                    io.BytesIO(media_id.encode()), mimetype="text/plain"
                ),
                fields="id",
            ).execute()

            logger.info(
                f"GoogleDrive: initialized folder {self.folder_id} for media {media_id}"
            )
            return True
        except Exception as e:
            logger.error(f"GoogleDrive initialize_media failed: {e}")
            return False

    def prepare_for_write(self, media_id: str) -> bool:
        return self.identify_media() == media_id

    def write_archive(self, media_id: str, stream: BinaryIO) -> str:
        from googleapiclient.http import MediaIoBaseUpload

        service = self._get_service()
        archive_name = f"{uuid.uuid4().hex}.tar"

        data = stream.read()
        if self.passphrase:
            data = encrypt(self.passphrase, data)

        file_name = self._archive_filename(archive_name)
        media_body = MediaIoBaseUpload(
            io.BytesIO(data),
            mimetype="application/octet-stream",
            chunksize=_CHUNK_SIZE,
            resumable=True,
        )
        request = service.files().create(
            body={"name": file_name, "parents": [self.folder_id]},
            media_body=media_body,
            fields="id",
        )

        response = None
        while response is None:
            _, response = request.next_chunk()

        file_id = response["id"]
        logger.info(f"GoogleDrive: uploaded archive {archive_name} → {file_id}")
        return file_id

    def read_archive(self, media_id: str, location_id: str) -> BinaryIO:
        request = self._get_service().files().get_media(fileId=location_id)
        data = request.execute()
        if self.passphrase:
            data = decrypt(self.passphrase, data)
        return io.BytesIO(data)

    def finalize_media(self, media_id: str):
        pass

    def get_utilization(self) -> Optional[float]:
        try:
            about = self._get_service().about().get(fields="storageQuota").execute()
            quota = about.get("storageQuota", {})
            used = int(quota.get("usage", 0))
            limit = int(quota.get("limit", 0))
            if limit > 0:
                return used / limit
        except Exception:
            pass
        return None

    def get_live_info(self, force: bool = False) -> Dict[str, Any]:
        info: Dict[str, Any] = {"online": False}
        try:
            about = (
                self._get_service().about().get(fields="user,storageQuota").execute()
            )
            quota = about.get("storageQuota", {})
            info["online"] = True
            info["account"] = about.get("user", {}).get("emailAddress")
            info["quota_used"] = int(quota.get("usage", 0))
            info["quota_total"] = int(quota.get("limit", 0))
            info["folder_id"] = self.folder_id
        except Exception:
            pass
        return info
