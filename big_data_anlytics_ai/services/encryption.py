"""Symmetric encryption for secrets at rest (Fernet)."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from config import get_settings


def _get_fernet() -> Fernet:
    settings = get_settings()
    key = settings.fernet_key
    if not key:
        raise RuntimeError(
            "FERNET_KEY not set. Generate with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    if len(key) != 44:
        derived = base64.urlsafe_b64encode(
            hashlib.sha256(key.encode()).digest()
        ).decode()
        key = derived
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_value(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Falha ao descriptografar valor") from exc
