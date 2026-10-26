import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.mark.parametrize("secret", ["s3cr3t-too-brief", "change-me-" + "x" * 40])
def test_a_weak_or_placeholder_jwt_secret_stops_startup(monkeypatch, secret):
    monkeypatch.setenv("JWT_SECRET", secret)
    with pytest.raises(ValidationError) as exc:
        Settings()
    assert secret not in str(exc.value)  # the error names the setting, not its value
