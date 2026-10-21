import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TenantKind(enum.StrEnum):
    platform = "platform"
    operator = "operator"


class Tenant(Base):
    """Tenant tree: one platform root (SELECTX) with operator tenants beneath it.

    Each operator maps 1:1 to a PestPac tenant.
    """

    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint("(kind = 'platform') = (parent_id IS NULL)", name="root_is_platform"),
        CheckConstraint(
            "pestpac_tenant_id IS NULL OR kind = 'operator'", name="pestpac_only_on_operator"
        ),
        CheckConstraint(
            "kind = 'platform' OR pestpac_tenant_id IS NOT NULL", name="operator_has_pestpac"
        ),
        Index(
            "uq_tenants_single_platform",
            "kind",
            unique=True,
            postgresql_where=text("kind = 'platform'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[TenantKind] = mapped_column(Enum(TenantKind, name="tenant_kind"))
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    pestpac_tenant_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
