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
