"""Symmetric encryption for secrets at rest (OAuth tokens). Fernet key from SECRET_ENCRYPTION_KEY."""
from cryptography.fernet import Fernet

from app.config import get_settings


class EncryptionUnavailableError(RuntimeError):
    """Raised when encryption is needed but SECRET_ENCRYPTION_KEY is not configured."""


def _fernet() -> Fernet:
    key = get_settings().secret_encryption_key
    if not key:
        raise EncryptionUnavailableError(
            "SECRET_ENCRYPTION_KEY is not set — required to store OAuth tokens. "
            "Generate one with: make secret-key"
        )
    return Fernet(key.encode())


def encrypt(plaintext: str) -> str:
    """Encrypt a string, returning a URL-safe token string."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a token produced by encrypt()."""
    return _fernet().decrypt(token.encode()).decode()
