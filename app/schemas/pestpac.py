import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models import ConnectionStatus

Credential = Field(min_length=1, max_length=255)


class PestPacConnectionWrite(BaseModel):
    """Secrets are write-only. Omit one to keep the stored value (required on first setup)."""

    client_id: str = Credential
    username: str = Credential
    client_secret: str | None = Field(default=None, min_length=1, max_length=1024)
    password: str | None = Field(default=None, min_length=1, max_length=1024)
    api_key: str | None = Field(default=None, min_length=4, max_length=1024)


class PestPacConnectionRead(BaseModel):
    operator_id: uuid.UUID
    pestpac_tenant_id: str | None
    configured: bool
    base_url: str | None = None
    client_id: str | None = None
    username: str | None = None
    has_client_secret: bool = False
    has_password: bool = False
    api_key_last4: str | None = None
    status: ConnectionStatus | None = None
    last_verified_at: datetime | None = None
    last_error: str | None = None
    pestpac_company_id: int | None = None
    pestpac_company_name: str | None = None
    updated_at: datetime | None = None
