import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from app.security import secrets

BAD_KEY = "x" * 64


@pytest.fixture
def bad_keys(monkeypatch):
    def use(value: str):
        monkeypatch.setenv("APP_ENCRYPTION_KEYS", value)
        get_settings.cache_clear()
        secrets.reset_cache()

    yield use
    monkeypatch.undo()
    get_settings.cache_clear()
    secrets.reset_cache()


def test_invalid_key_names_the_setting_without_echoing_it(bad_keys):
    bad_keys(BAD_KEY)
    with pytest.raises(RuntimeError) as exc:
        secrets.validate_keys()
    message = str(exc.value)
    assert "APP_ENCRYPTION_KEYS key #1" in message
    assert "got 64" in message
    assert "Fernet.generate_key" in message
    assert BAD_KEY not in message


def test_bad_rotation_key_is_reported_by_position(bad_keys):
    good = "Q2PYvKXuaXz5O3b4pV3-6dmgHAx5k5hvYb7Qm9H8u2Y="
    bad_keys(f"{good},{BAD_KEY}")
    with pytest.raises(RuntimeError, match="key #2"):
        secrets.validate_keys()


def test_missing_key_is_reported(bad_keys):
    bad_keys("")
    with pytest.raises(RuntimeError, match="APP_ENCRYPTION_KEYS is not set"):
        secrets.validate_keys()


def test_api_refuses_to_start_with_a_bad_key(bad_keys):
    bad_keys(BAD_KEY)
    # Entering the client runs the lifespan startup.
    with pytest.raises(RuntimeError, match="APP_ENCRYPTION_KEYS"), TestClient(app):
        pass
