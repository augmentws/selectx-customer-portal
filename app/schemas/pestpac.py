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


# PestPac field -> (our attribute, max length matching the bill_tos column).
_BILL_TO_FIELDS: dict[str, tuple[str, int]] = {
    "BillToCode": ("pestpac_bill_to_code", 50),
    "Company": ("pestpac_company", 200),
    "Address": ("address", 200),
    "Address2": ("address2", 200),
    "City": ("city", 100),
    "State": ("state", 50),
    "Zip": ("zip", 20),
    "Phone": ("phone", 50),
    "Type": ("pestpac_type", 100),
}


class PestPacBillToDetails(BaseModel):
    """Identifying details of a PestPac bill-to. Only these fields are kept; the rest of the
    GET /BillTos/{id} response (balances, credit and collection data, contacts) is discarded."""

    pestpac_bill_to_id: int
    pestpac_bill_to_code: str | None = None
    pestpac_company: str | None = None
    address: str | None = None
    address2: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    phone: str | None = None
    pestpac_type: str | None = None

    @classmethod
    def from_api(cls, body: dict) -> PestPacBillToDetails:
        values: dict[str, object] = {"pestpac_bill_to_id": body["BillToID"]}
        for source, (attr, max_len) in _BILL_TO_FIELDS.items():
            raw = body.get(source)
            text = str(raw).strip() if raw is not None else ""
            values[attr] = text[:max_len] or None
        return cls.model_validate(values)

    @property
    def suggested_name(self) -> str:
        """`{Company} · {Address}, {City}`: Company alone repeats across a chain's bill-tos."""
        place = ", ".join(p for p in (self.address, self.city) if p)
        parts = [p for p in (self.pestpac_company, place) if p]
        return (" · ".join(parts) or f"BillTo {self.pestpac_bill_to_id}")[:200]


class BillToLookup(BaseModel):
    details: PestPacBillToDetails
    suggested_name: str
    # Set when this BillToID is already onboarded under the operator.
    onboarded_bill_to_id: uuid.UUID | None = None
    onboarded_company_id: uuid.UUID | None = None


_LOCATION_TEXT_FIELDS: dict[str, tuple[str, int]] = {
    "LocationCode": ("pestpac_location_code", 50),
    "Company": ("pestpac_company", 200),
    "Address": ("address", 200),
    "Address2": ("address2", 200),
    "City": ("city", 100),
    "State": ("state", 50),
    "Zip": ("zip", 20),
    "Phone": ("phone", 50),
    "Email": ("email", 320),
    "Type": ("pestpac_type", 100),
    "AccountType": ("account_type", 50),
}


def _float_or_none(value: object) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except TypeError, ValueError:
        return None


class PestPacLocationDetails(BaseModel):
    """A location from GET /BillTos/{id}/locations/pageable. Contact names, user-defined fields
    (which include staff names), and marketing flags are discarded."""

    pestpac_location_id: int
    pestpac_bill_to_id: int
    pestpac_location_code: str | None = None
    pestpac_company: str | None = None
    address: str | None = None
    address2: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    phone: str | None = None
    email: str | None = None
    pestpac_type: str | None = None
    account_type: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    pestpac_active: bool = True

    @classmethod
    def from_api(cls, body: dict) -> PestPacLocationDetails:
        values: dict[str, object] = {
            "pestpac_location_id": body["LocationID"],
            "pestpac_bill_to_id": body["BillToID"],
            "latitude": _float_or_none(body.get("Latitude")),
            "longitude": _float_or_none(body.get("Longitude")),
            "pestpac_active": body.get("Active") is not False,
        }
        for source, (attr, max_len) in _LOCATION_TEXT_FIELDS.items():
            raw = body.get(source)
            text = str(raw).strip() if raw is not None else ""
            values[attr] = text[:max_len] or None
        return cls.model_validate(values)


class LocationSyncSummary(BaseModel):
    total: int
    added: int
    updated: int
    removed: int


_SERVICE_ORDER_TEXT_FIELDS: dict[str, tuple[str, int | None]] = {
    "OrderNumber": ("order_number", 50),
    "ServiceCode": ("service_code", 100),
    "Description": ("description", 500),
    "Tech1": ("tech_name", 100),
    # Instructions are free text; no cap.
    "LocationInstructions": ("location_instructions", None),
    "ServiceInstructions": ("service_instructions", None),
    "OrderInstructions": ("order_instructions", None),
}


def _pestpac_local_datetime(value: object) -> datetime | None:
    """PestPac datetimes are tenant wall-clock time without an offset; keep them as such."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except TypeError, ValueError:
        return None


class PestPacServiceOrderDetails(BaseModel):
    """A service order from GET /ServiceOrders/{id} or /Locations/{id}/serviceOrders. Only the
    agreed fields are kept: no pricing, tax, scheduling windows, or user-defined fields."""

    pestpac_order_id: int
    pestpac_location_id: int
    pestpac_bill_to_id: int
    order_number: str | None = None
    service_code: str | None = None
    description: str | None = None
    work_date: datetime | None = None
    tech_name: str | None = None
    tech_id: int | None = None
    location_instructions: str | None = None
    service_instructions: str | None = None
    order_instructions: str | None = None
    posted: bool = False

    @classmethod
    def from_api(cls, body: dict) -> PestPacServiceOrderDetails:
        values: dict[str, object] = {
            "pestpac_order_id": body["OrderID"],
            "pestpac_location_id": body["LocationID"],
            "pestpac_bill_to_id": body["BillToID"],
            "work_date": _pestpac_local_datetime(body.get("WorkDate")),
            "tech_id": _int_or_none(body.get("TechID1")),
            "posted": body.get("Posted") is True,
        }
        for source, (attr, max_len) in _SERVICE_ORDER_TEXT_FIELDS.items():
            raw = body.get(source)
            text = str(raw).strip() if raw is not None else ""
            values[attr] = (text[:max_len] if max_len else text) or None
        return cls.model_validate(values)


class ServiceOrderSyncCounts(BaseModel):
    added: int = 0
    updated: int = 0
    closed: int = 0
    reopened: int = 0
    newly_posted: int = 0
    skipped_other_bill_to: int = 0
    technicians_resolved: int = 0
    technicians_unresolved: int = 0


class PestPacTechnicianDetails(BaseModel):
    """Identifying fields from GET /lookups/Employees/technicians/{techId}. Everything else in
    that record (email, phone, birth date, emergency contacts, access settings) is discarded."""

    pestpac_tech_id: int
    pestpac_employee_id: int | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    active: bool = True

    @classmethod
    def from_api(cls, body: dict) -> PestPacTechnicianDetails:
        def text(key: str) -> str | None:
            raw = body.get(key)
            return (str(raw).strip()[:100] or None) if raw is not None else None

        return cls(
            pestpac_tech_id=body["TechID"],
            pestpac_employee_id=_int_or_none(body.get("EmployeeID")),
            username=text("Username"),
            first_name=text("FirstName"),
            last_name=text("LastName"),
            active=body.get("Active") is not False,
        )


class PestPacNoteContent(BaseModel):
    """A note's content, as in GET /Locations/{id}/notes items and GET /Notes/{id}."""

    pestpac_note_id: int
    note_date: datetime | None = None
    note_code: str | None = None
    note: str | None = None
    created_by_user: str | None = None
    show_on_portal: bool = False
    alert_expiration_date: datetime | None = None

    @classmethod
    def from_api(cls, body: dict) -> PestPacNoteContent:
        def text(key: str, max_len: int | None) -> str | None:
            raw = body.get(key)
            value = str(raw).strip() if raw is not None else ""
            return (value[:max_len] if max_len else value) or None

        return cls(
            pestpac_note_id=body["NoteID"],
            note_date=_pestpac_local_datetime(body.get("NoteDate")),
            note_code=text("NoteCode", 50),
            note=text("Note", None),
            created_by_user=text("CreatedByUser", 100),
            show_on_portal=body.get("ShowOnPortal") is True,
            alert_expiration_date=_pestpac_local_datetime(body.get("AlertExpirationDate")),
        )


# GET /Notes/{id} Associations key -> Note column.
NOTE_ASSOCIATIONS: dict[str, str] = {
    "LocationID": "pestpac_location_id",
    "BillToID": "pestpac_bill_to_id",
    "OrderID": "pestpac_order_id",
    "InvoiceID": "pestpac_invoice_id",
    "ContactID": "pestpac_contact_id",
    "TaskID": "pestpac_task_id",
    "SalesLeadID": "pestpac_sales_lead_id",
    "CallID": "pestpac_call_id",
}


class PestPacNoteDetails(PestPacNoteContent):
    """GET /Notes/{id}: content plus what the note is associated with."""

    associations: dict[str, int | None]

    @classmethod
    def from_api(cls, body: dict) -> PestPacNoteDetails:
        raw = body.get("Associations") or {}
        content = PestPacNoteContent.from_api(body)
        return cls(
            **content.model_dump(),
            associations={
                column: _int_or_none(raw.get(key)) for key, column in NOTE_ASSOCIATIONS.items()
            },
        )


class NoteSyncCounts(BaseModel):
    total: int = 0
    added: int = 0
    updated: int = 0
    details_fetched: int = 0
    linked_to_orders: int = 0
    invoices_found: int = 0
