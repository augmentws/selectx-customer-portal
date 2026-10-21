import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.schemas.auth import PASSWORD_MIN_LENGTH
from app.security.permissions import RoleScope

Name = Field(min_length=1, max_length=200)


class PartialUpdate(BaseModel):
    """Only fields present in the request are changed. Fields in `_not_nullable` may be omitted
    but not sent as null."""

    _not_nullable: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _reject_explicit_nulls(self):
        nulls = [
            f for f in self._not_nullable if f in self.model_fields_set and getattr(self, f) is None
        ]
        if nulls:
            raise ValueError(f"{', '.join(nulls)} cannot be null")
        return self


class OperatorCreate(BaseModel):
    name: str = Name
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    pestpac_tenant_id: str | None = Field(default=None, min_length=1, max_length=64)


class OperatorUpdate(PartialUpdate):
    _not_nullable = ("name", "is_active")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    pestpac_tenant_id: str | None = Field(default=None, min_length=1, max_length=64)
    is_active: bool | None = None


class OperatorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    pestpac_tenant_id: str | None
    is_active: bool
    created_at: datetime


class CompanyCreate(BaseModel):
    name: str = Name


class CompanyUpdate(PartialUpdate):
    _not_nullable = ("name", "is_active")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    operator_id: uuid.UUID
    name: str
    is_active: bool
    created_at: datetime


class BillToCreate(BaseModel):
    pestpac_bill_to_id: int = Field(gt=0)
    name: str = Name
    description: str | None = Field(default=None, max_length=1000)


class BillToUpdate(PartialUpdate):
    _not_nullable = ("name", "is_active")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


class BillToRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    operator_id: uuid.UUID
    company_id: uuid.UUID
    pestpac_bill_to_id: int
    name: str
    description: str | None
    is_active: bool
    onboarded_at: datetime
    onboarded_by: uuid.UUID | None


class MemberCreate(BaseModel):
    email: EmailStr
    role: str
    # Required when the email has no account yet; the user must change it at first sign-in.
    temporary_password: str | None = Field(
        default=None, min_length=PASSWORD_MIN_LENGTH, max_length=256
    )


class MemberUpdate(BaseModel):
    role: str


class MemberRead(BaseModel):
    user_id: uuid.UUID
    email: EmailStr
    tenant_id: uuid.UUID
    role: str
    must_change_password: bool
    created_at: datetime


class MemberCreated(MemberRead):
    user_created: bool


class PermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    description: str


class RoleRead(BaseModel):
    name: str
    description: str
    scope: RoleScope
    permissions: list[str]
