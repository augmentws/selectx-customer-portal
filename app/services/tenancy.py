import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BillTo, Company, Tenant, TenantKind
from app.schemas.tenancy import (
    BillToCreate,
    BillToUpdate,
    CompanyCreate,
    CompanyUpdate,
    OperatorCreate,
    OperatorUpdate,
)
from app.services.rbac import get_platform_tenant


class ConflictError(Exception):
    pass


def _apply(obj: object, data: OperatorUpdate | CompanyUpdate | BillToUpdate) -> None:
    for name in data.model_fields_set:
        setattr(obj, name, getattr(data, name))


# Operators


def get_operator(db: Session, operator_id: uuid.UUID) -> Tenant | None:
    tenant = db.get(Tenant, operator_id)
    return tenant if tenant is not None and tenant.kind == TenantKind.operator else None


def list_operators(db: Session, only_ids: set[uuid.UUID] | None) -> list[Tenant]:
    """`only_ids=None` lists every operator."""
    query = select(Tenant).where(Tenant.kind == TenantKind.operator).order_by(Tenant.name)
    if only_ids is not None:
        query = query.where(Tenant.id.in_(only_ids))
    return list(db.scalars(query))


def _check_pestpac_tenant_free(
    db: Session, pestpac_tenant_id: str | None, exclude: uuid.UUID | None = None
) -> None:
    if pestpac_tenant_id is None:
        return
    query = select(Tenant).where(Tenant.pestpac_tenant_id == pestpac_tenant_id)
    if exclude is not None:
        query = query.where(Tenant.id != exclude)
    if db.scalar(query) is not None:
        raise ConflictError(f"PestPac tenant {pestpac_tenant_id} is already linked to an operator")


def create_operator(db: Session, data: OperatorCreate) -> Tenant:
    if db.scalar(select(Tenant).where(Tenant.slug == data.slug)) is not None:
        raise ConflictError(f"Slug {data.slug!r} is already in use")
    _check_pestpac_tenant_free(db, data.pestpac_tenant_id)
    operator = Tenant(
        parent_id=get_platform_tenant(db).id,
        kind=TenantKind.operator,
        name=data.name,
        slug=data.slug,
        pestpac_tenant_id=data.pestpac_tenant_id,
    )
    db.add(operator)
    db.commit()
    return operator


def update_operator(db: Session, operator: Tenant, data: OperatorUpdate) -> Tenant:
    if "pestpac_tenant_id" in data.model_fields_set:
        _check_pestpac_tenant_free(db, data.pestpac_tenant_id, exclude=operator.id)
    _apply(operator, data)
    db.commit()
    return operator


# Companies


def list_companies(db: Session, operator_id: uuid.UUID) -> list[Company]:
    return list(
        db.scalars(select(Company).where(Company.operator_id == operator_id).order_by(Company.name))
    )


def create_company(db: Session, operator: Tenant, data: CompanyCreate) -> Company:
    company = Company(operator_id=operator.id, name=data.name)
    db.add(company)
    db.commit()
    return company


def update_company(db: Session, company: Company, data: CompanyUpdate) -> Company:
    _apply(company, data)
    db.commit()
    return company


# Bill-tos


def list_bill_tos(db: Session, company_id: uuid.UUID) -> list[BillTo]:
    return list(
        db.scalars(
            select(BillTo)
            .where(BillTo.company_id == company_id)
            .order_by(BillTo.pestpac_bill_to_id)
        )
    )


def onboard_bill_to(
    db: Session, company: Company, data: BillToCreate, onboarded_by: uuid.UUID
) -> BillTo:
    existing = db.scalar(
        select(BillTo).where(
            BillTo.operator_id == company.operator_id,
            BillTo.pestpac_bill_to_id == data.pestpac_bill_to_id,
        )
    )
    if existing is not None:
        owner = "this company" if existing.company_id == company.id else "another company"
        raise ConflictError(
            f"PestPac bill-to {data.pestpac_bill_to_id} is already onboarded to {owner}"
        )
    bill_to = BillTo(
        operator_id=company.operator_id,
        company_id=company.id,
        pestpac_bill_to_id=data.pestpac_bill_to_id,
        name=data.name,
        description=data.description,
        onboarded_by=onboarded_by,
    )
    db.add(bill_to)
    db.commit()
    return bill_to


def update_bill_to(db: Session, bill_to: BillTo, data: BillToUpdate) -> BillTo:
    _apply(bill_to, data)
    db.commit()
    return bill_to
