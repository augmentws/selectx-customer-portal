import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.schemas.tenancy import ServiceOrderRead


class InvoiceLineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: int
    service_code: str | None
    description: str | None
    cost: Decimal | None
    unit_price: Decimal | None
    quantity: Decimal | None
    extended_price: Decimal | None
    taxable: bool | None
    gl_code: str | None


class InvoiceRead(BaseModel):
    """A stored PestPac invoice. Amounts are decimals (serialized as strings)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bill_to_id: uuid.UUID
    location_id: uuid.UUID | None
    service_order_id: uuid.UUID | None
    technician_id: uuid.UUID | None
    # Position-1 technician's name, when resolved.
    technician_name: str | None
    pestpac_invoice_id: int
    pestpac_location_id: int | None
    pestpac_bill_to_id: int
    pestpac_setup_id: int | None
    pestpac_order_id: int | None
    pestpac_tech_id: int | None
    invoice_number: str | None
    order_number: str | None
    service_code: str | None
    description: str | None
    total: Decimal | None
    balance: Decimal | None
    service_fee_total: Decimal | None
    cost: Decimal | None
    # PestPac local wall-clock times.
    invoice_date: datetime | None
    work_date: datetime | None
    due_date: datetime | None
    order_date: datetime | None
    time_range: str | None
    duration: int | None
    invoice_type: str | None
    order_type: str | None
    origin: str | None
    location_instructions: str | None
    service_instructions: str | None
    order_instructions: str | None
    technician_comment: str | None
    batch_number: int | None
    removed_at: datetime | None
    pestpac_fetched_at: datetime
    lines: list[InvoiceLineRead]


class InvoicedOrderRead(InvoiceRead):
    """An invoice with the service order it bills (null when we don't hold the order)."""

    location_name: str | None
    service_order: ServiceOrderRead | None


class InvoicedOrderPage(BaseModel):
    items: list[InvoicedOrderRead]
    total: int
    limit: int
    offset: int


class InvoicePage(BaseModel):
    items: list[InvoiceRead]
    total: int
    limit: int
    offset: int
