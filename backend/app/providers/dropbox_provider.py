import io
import json
import uuid
from typing import Optional, BinaryIO, Dict, Any

from loguru import logger

from .base import AbstractStorageProvider
from .encryption import get_secret, encrypt, decrypt, obfuscated_name

_CHUNK_SIZE = 128 * 1024 * 1024  # 128 MB — Dropbox max per session chunk
_SMALL_FILE_THRESHOLD = 150 * 1024 * 1024  # files ≤ 150 MB in one shot


def _load_setting(key: str) -> Optional[str]:
    try:
        from app.db.database import SessionLocal
        from app.db import models

        with SessionLocal() as db:
            r = (
                db.query(models.SystemSetting)
                .filter(models.SystemSetting.key == key)
                .first()
            )
            return r.value if r else None
    except Exception:
        return None


class DropboxProvider(AbstractStorageProvider):
    provider_id = "dropbox"
    name = "Dropbox"
    description = "Store archives in a Dropbox folder via OAuth2."
    capabilities = {
        "supports_random_access": True,
        "is_offline_capable": False,
        "supports_hardware_encryption": False,
    }
    config_schema = {
        "credential_key": {
            "type": "string",
            "title": "OAuth Credential Key",
            "description": "Internal reference key for stored OAuth tokens. Set via 'Connect with Dropbox'.",
        },
        "root_folder": {
            "type": "string",
            "title": "Root Folder Path",
            "description": "Dropbox path where archives are stored, e.g. /TapeHoard/MyBackup. Auto-set after Initialize Media.",
        },
        "encryption_secret_name": {
            "type": "string",
            "title": "Encryption Secret",
            "description": "Name of a secret in the settings keystore used for client-side AES-256-GCM encryption.",
        },
        "obfuscate_filenames": {
            "type": "boolean",
            "title": "Obfuscate Filenames",
            "description": "Store files as SHA-256 hashes in Dropbox to hide metadata.",
            "default": False,
        },
    }

    def __init__(self, config: Dict[str, Any]):
        self.credential_key: Optional[str] = config.get("credential_key")
        self.root_folder: Optional[str] = config.get("root_folder")
        self._dbx = None
        self.passphrase = get_secret(config.get("encryption_secret_name"))
        self.obfuscate: bool = bool(config.get("obfuscate_filenames", False))

    # --- Dropbox client helper ---

    def _get_client(self):
        if self._dbx is None:
            if not self.credential_key:
                raise ValueError(
                    "No OAuth credential configured for this Dropbox media."
                )

            cred_json = _load_setting(self.credential_key)
            if not cred_json:
                raise ValueError(f"OAuth credential '{self.credential_key}' not found.")

            cred_data = json.loads(cred_json)
            app_key = get_secret("dropbox_app_key")
            app_secret = get_secret("dropbox_app_secret")

            import dropbox

            self._dbx = dropbox.Dropbox(
                oauth2_access_token=cred_data.get("access_token"),
                oauth2_refresh_token=cred_data.get("refresh_token"),
                app_key=app_key,
                app_secret=app_secret,
            )
        return self._dbx

    def _archive_path(self, name: str) -> str:
        dest_name = obfuscated_name(name) if self.obfuscate else name
        return f"{self.root_folder}/archives/{dest_name}"

    # --- AbstractStorageProvider implementation ---

    def get_name(self) -> str:
        return "Dropbox"

    def check_online(self, force: bool = False) -> bool:
        try:
            self._get_client().users_get_current_account()
            return True
        except Exception:
            return False

    def check_existing_data(self) -> bool:
        if not self.root_folder:
            return False
        try:
            result = self._get_client().files_list_folder(
                f"{self.root_folder}/archives"
            )
            return bool(result.entries)
        except Exception:
            return False

    def identify_media(self, allow_intrusive=True) -> Optional[str]:
        if not self.root_folder:
            return None
        try:
            md, resp = self._get_client().files_download(
                f"{self.root_folder}/.tapehoard_id"
            )
            return resp.content.decode("utf-8").strip()
        except Exception as e:
            logger.error(f"Dropbox identify_media failed: {e}")
            return None

    def initialize_media(self, media_id: str) -> bool:
        try:
            import dropbox as dropbox_sdk
            import dropbox.files

            dbx = self._get_client()
            self.root_folder = f"/TapeHoard/{media_id}"

            # Create folder hierarchy
            for path in [self.root_folder, f"{self.root_folder}/archives"]:
                try:
                    dbx.files_create_folder_v2(path)
                except Exception:
                    pass  # already exists

            # Write identity marker
            dbx.files_upload(
                media_id.encode("utf-8"),
                f"{self.root_folder}/.tapehoard_id",
                mode=dropbox_sdk.files.WriteMode("overwrite"),
            )

            logger.info(
                f"Dropbox: initialized folder {self.root_folder} for media {media_id}"
            )
            return True
        except Exception as e:
            logger.error(f"Dropbox initialize_media failed: {e}")
            return False

    def prepare_for_write(self, media_id: str) -> bool:
        return self.identify_media() == media_id

    def write_archive(self, media_id: str, stream: BinaryIO) -> str:
        import dropbox as dbx_sdk
        import dropbox.files

        dbx = self._get_client()
        files = dbx_sdk.files
        archive_name = f"{uuid.uuid4().hex}.tar"
        dest_path = self._archive_path(archive_name)

        data = stream.read()
        if self.passphrase:
            data = encrypt(self.passphrase, data)
        size = len(data)

        if size <= _SMALL_FILE_THRESHOLD:
            dbx.files_upload(
                data,
                dest_path,
                mode=files.WriteMode("overwrite"),
            )
        else:
            # Chunked session upload
            session = dbx.files_upload_session_start(data[:_CHUNK_SIZE])
            cursor = files.UploadSessionCursor(
                session_id=session.session_id, offset=_CHUNK_SIZE
            )
            offset = _CHUNK_SIZE
            while offset < size:
                chunk = data[offset : offset + _CHUNK_SIZE]
                is_last = (offset + len(chunk)) >= size
                if is_last:
                    commit = files.CommitInfo(
                        path=dest_path, mode=files.WriteMode("overwrite")
                    )
                    dbx.files_upload_session_finish(chunk, cursor, commit)
                else:
                    dbx.files_upload_session_append_v2(chunk, cursor)
                    cursor = files.UploadSessionCursor(
                        session_id=cursor.session_id, offset=cursor.offset + len(chunk)
                    )
                offset += len(chunk)

        logger.info(f"Dropbox: uploaded archive {archive_name} to {dest_path}")
        return dest_path

    def read_archive(self, media_id: str, location_id: str) -> BinaryIO:
        _, resp = self._get_client().files_download(location_id)
        data = resp.content
        if self.passphrase:
            data = decrypt(self.passphrase, data)
        return io.BytesIO(data)

    def finalize_media(self, media_id: str):
        pass

    def get_utilization(self) -> Optional[float]:
        try:
            usage = self._get_client().users_get_space_usage()
            used = usage.used
            alloc = usage.allocation.get_individual()
            total = alloc.allocated if alloc else 0
            if total > 0:
                return used / total
        except Exception:
            pass
        return None

    def get_live_info(self, force: bool = False) -> Dict[str, Any]:
        info: Dict[str, Any] = {"online": False}
        try:
            dbx = self._get_client()
            acct = dbx.users_get_current_account()
            usage = dbx.users_get_space_usage()
            alloc = usage.allocation.get_individual()
            info["online"] = True
            info["account"] = acct.email
            info["quota_used"] = usage.used
            info["quota_total"] = alloc.allocated if alloc else 0
            info["root_folder"] = self.root_folder
        except Exception:
            pass
        return info
