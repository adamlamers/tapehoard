"""
Shared AES-256-GCM encryption helpers used by all cloud storage providers.

Wire format: [Salt 16 B][Nonce 12 B][GCM Tag 16 B][Ciphertext …]
"""

import hashlib
import os
from typing import Optional


def get_secret(name: Optional[str]) -> Optional[str]:
    """Resolve a named secret from the settings keystore."""
    if not name:
        return None
    try:
        import json
        from app.db.database import SessionLocal
        from app.db import models

        with SessionLocal() as db:
            r = (
                db.query(models.SystemSetting)
                .filter(models.SystemSetting.key == "secrets")
                .first()
            )
            if r and r.value:
                return json.loads(r.value).get(name)
    except Exception:
        pass
    return None


def derive_key(passphrase: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256 → 256-bit AES key."""
    from Crypto.Protocol.KDF import PBKDF2
    from Crypto.Hash import SHA256

    return PBKDF2(passphrase, salt, dkLen=32, count=100000, hmac_hash_module=SHA256)


def encrypt(passphrase: str, data: bytes) -> bytes:
    """AES-256-GCM encrypt. Returns Salt‖Nonce‖Tag‖Ciphertext."""
    from Crypto.Cipher import AES

    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = derive_key(passphrase, salt)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(data)
    return salt + nonce + tag + ciphertext


def decrypt(passphrase: str, payload: bytes) -> bytes:
    """AES-256-GCM decrypt. Expects Salt‖Nonce‖Tag‖Ciphertext."""
    from Crypto.Cipher import AES

    salt, nonce, tag, ciphertext = (
        payload[:16],
        payload[16:28],
        payload[28:44],
        payload[44:],
    )
    key = derive_key(passphrase, salt)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag)


def obfuscated_name(name: str) -> str:
    """SHA-256 hash of *name* with two-level directory sharding."""
    h = hashlib.sha256(name.encode()).hexdigest()
    return f"{h[:2]}/{h[2:4]}/{h}"
