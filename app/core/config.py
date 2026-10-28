from datetime import date
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Settings hold secrets: a validation error names the setting, never its value.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    database_url: str = (
        "postgresql+psycopg://customer_portal:customer_portal@localhost:5433/customer_portal"
    )

    # Signs every token: anyone who knows it can mint sessions. At least 32 characters, and never
    # the .env.example placeholder (checked below), so a copied example can't go live.
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14

    # Sign-in lockout: this many failures for one email within the window locks it for
    # login_lock_minutes (counted per email, whether or not it has an account).
    login_max_failures: int = Field(default=5, ge=1)
    login_failure_window_minutes: int = Field(default=15, ge=1)
    login_lock_minutes: int = Field(default=15, ge=1)
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

    # Location documents synced from PestPac: those dated on or after this day.
    pestpac_documents_start_date: date = date(2025, 9, 25)
    # Files larger than this are listed but not stored.
    document_max_bytes: int = Field(default=50_000_000, ge=1)

    # Object storage, through the S3 API only (MinIO locally; R2 or S3 elsewhere). An empty
    # bucket means storage isn't configured, and document files aren't synced.
    s3_endpoint_url: str = ""  # empty for AWS S3
    s3_region: str = "us-east-1"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_bucket: str = ""

    # Background worker (python -m app.worker).
    # False pauses everything that syncs with PestPac: webhooks are still captured, but the worker
    # neither handles them nor runs sync jobs (both wait, and run once this is true again), and
    # sync requests are refused. One-off calls people make (credentials, onboarding) still work.
    sync_active: bool = True
    worker_poll_seconds: float = Field(default=5.0, gt=0)
    sync_job_stale_minutes: int = Field(default=10, ge=1)
    sync_job_max_attempts: int = Field(default=3, ge=1)

    # PestPac webhooks (POST /v1/webhooks/pestpac).
    webhook_max_body_bytes: int = Field(default=1_000_000, ge=1)
    webhook_raw_retention_days: int = Field(default=30, ge=1)
    # PestPac sends an invoice's create and updates seconds apart. Its events wait until this
    # long after the first one, or until this many updates arrive, then share one fetch.
    invoice_webhook_wait_minutes: int = Field(default=5, ge=0)
    invoice_webhook_max_updates: int = Field(default=3, ge=1)

    # OpenRouter (LLM data clean-up). One platform-wide key; models are chosen per task or call.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # OpenRouter model id used when a call doesn't name one; empty means every call must.
    openrouter_default_model: str = ""
    openrouter_timeout_seconds: float = Field(default=60.0, gt=0)
    openrouter_max_retries: int = Field(default=2, ge=0)
    openrouter_app_title: str = "SELECTX Customer Portal"
    # Logs prompts and completions (customer data). Local debugging only.
    openrouter_debug_bodies: bool = False

    @field_validator("jwt_secret")
    @classmethod
    def _not_the_placeholder(cls, value: str) -> str:
        if value.startswith("change-me"):
            raise ValueError("JWT_SECRET is the .env.example placeholder; set a random value")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
