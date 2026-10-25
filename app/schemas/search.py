import uuid
from typing import Literal

from pydantic import BaseModel

SearchKind = Literal["operator", "company", "bill_to", "location", "service_order", "invoice"]


class SearchHit(BaseModel):
    kind: SearchKind
    id: uuid.UUID
    title: str
    # A second line: address, owning company, or the order's location.
    detail: str | None = None
    # Orders and invoices have no page of their own; they open on their location's page.
    location_id: uuid.UUID | None = None


class SearchResults(BaseModel):
    """Hits grouped by kind in the order above, each kind capped at `limit`."""

    query: str
    items: list[SearchHit]
