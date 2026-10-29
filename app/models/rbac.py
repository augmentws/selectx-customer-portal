import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Table,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.security.permissions import RoleScope

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_code", ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True),
)


class Permission(Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str] = mapped_column(String(255))


class Role(Base):
    """A named set of permissions. `tenant_id` NULL means a system role available everywhere;
    the column exists so operators can define custom roles later."""

    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_id_name"),
        Index(
            "uq_roles_system_name", "name", unique=True, postgresql_where=text("tenant_id IS NULL")
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(255))
    scope: Mapped[RoleScope] = mapped_column(Enum(RoleScope, name="role_scope"))

    permissions: Mapped[list[Permission]] = relationship(secondary=role_permissions)


class Membership(Base):
    """Grants a role on a tenant. Applies to that tenant and everything beneath it."""

    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id", name="uq_memberships_user_tenant"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    role: Mapped[Role] = relationship()


class CompanyMembership(Base):
    """Grants a company-scoped role (a customer's user) on one company. Kept apart from
    `memberships` so a company grant can never be read as a grant on its operator."""

    __tablename__ = "company_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "company_id", name="uq_company_memberships_user_company"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), index=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    role: Mapped[Role] = relationship()
