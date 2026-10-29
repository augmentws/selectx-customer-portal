import uuid

from pydantic import BaseModel, EmailStr, Field

from app.models import TenantKind

PASSWORD_MIN_LENGTH = 12


class LoginRequest(BaseModel):
    email: EmailStr
    # Capped like new passwords: every attempt is an Argon2 hash, so a huge one costs CPU.
    password: str = Field(max_length=256)


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


class CompanyGrant(BaseModel):
    """A customer user's role on one company; it applies only to that company."""

    company_id: uuid.UUID
    company_name: str
    operator_id: uuid.UUID
    role: str
    permissions: list[str]


class MeRead(BaseModel):
    id: uuid.UUID
    email: EmailStr
    must_change_password: bool
    # A grant on the platform tenant applies to every operator.
    memberships: list[MembershipGrant]
    company_memberships: list[CompanyGrant]
