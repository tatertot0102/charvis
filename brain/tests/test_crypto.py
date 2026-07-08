"""Unit tests for Fernet encryption of secrets at rest (no DB)."""
import pytest
from cryptography.fernet import Fernet

from app.config import get_settings
from app.security import crypto


def test_encrypt_decrypt_roundtrip(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(get_settings(), "secret_encryption_key", key)
    ciphertext = crypto.encrypt("super-secret-refresh-token")
    assert ciphertext != "super-secret-refresh-token"
    assert crypto.decrypt(ciphertext) == "super-secret-refresh-token"


def test_encrypt_requires_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "secret_encryption_key", None)
    with pytest.raises(crypto.EncryptionUnavailableError):
        crypto.encrypt("x")
