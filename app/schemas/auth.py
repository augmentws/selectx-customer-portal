import uuid

from pydantic import BaseModel, EmailStr, Field

from app.models import TenantKind

PASSWORD_MIN_LENGTH = 12


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=256)


class MembershipGrant(BaseModel):
    tenant_id: uuid.UUID
    tenant_name: str
    tenant_kind: TenantKind
    role: str
    permissions: list[str]


class MeRead(BaseModel):
    id: uuid.UUID
    email: EmailStr
    must_change_password: bool
    # A grant on the platform tenant applies to every operator.
    memberships: list[MembershipGrant]
