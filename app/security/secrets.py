"""Encryption for third-party credentials stored in the database (e.g. PestPac secrets).

`APP_ENCRYPTION_KEYS` is a comma-separated list of Fernet keys. The first key encrypts;
all keys decrypt, so a key can be rotated by prepending a new one and re-saving.
Generate a key with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings


class SecretDecryptionError(Exception):
    pass


@lru_cache
def _fernet() -> MultiFernet:
    keys = [k.strip() for k in get_settings().app_encryption_keys.split(",") if k.strip()]
    if not keys:
        raise RuntimeError("APP_ENCRYPTION_KEYS is not set")
    return MultiFernet([Fernet(k) for k in keys])


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretDecryptionError(
            "Stored secret can't be decrypted with the configured APP_ENCRYPTION_KEYS"
        ) from exc


def reset_cache() -> None:
    """For tests and key rotation within a running process."""
    _fernet.cache_clear()
