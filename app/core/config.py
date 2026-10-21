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


@lru_cache
def get_settings() -> Settings:
    return Settings()
