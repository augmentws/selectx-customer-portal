from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = (
        "postgresql+psycopg://customer_portal:customer_portal@localhost:5433/customer_portal"
    )

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14

    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: str | None = None

    web_origin: str = "http://localhost:3001"

    # Comma-separated Fernet keys; the first encrypts. See app/security/secrets.py.
    app_encryption_keys: str = ""

    pestpac_token_url: str = "https://is.workwave.com/oauth2/token?scope=openid"
    pestpac_default_base_url: str = "https://api.workwave.com/pestpac/v1"
    # Log PestPac request/response bodies. They contain customer data; local debugging only.
    pestpac_debug_bodies: bool = False
    # Page size for PestPac's pageable endpoints, and a ceiling on pages per sync.
    pestpac_page_size: int = Field(default=50, ge=1, le=500)
    pestpac_max_pages: int = Field(default=200, ge=1)

    # Background worker (python -m app.worker).
    worker_poll_seconds: float = Field(default=5.0, gt=0)
    sync_job_stale_minutes: int = Field(default=10, ge=1)
    sync_job_max_attempts: int = Field(default=3, ge=1)

    # PestPac webhooks (POST /v1/webhooks/pestpac).
    webhook_max_body_bytes: int = Field(default=1_000_000, ge=1)
    webhook_raw_retention_days: int = Field(default=30, ge=1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
