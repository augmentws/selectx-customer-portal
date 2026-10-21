from functools import lru_cache

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
