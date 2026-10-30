import uuid

from pydantic import BaseModel

from app.models import ContactLink, ContactRole


class ContactRead(BaseModel):
    """A contact in its role at a location or bill-to."""

    # The link's id: the same contact appears once per role and object.
    id: uuid.UUID
    contact_id: uuid.UUID
    role: ContactRole
    name: str | None
    email: str | None
    phone: str | None
    # Where it came from, e.g. "restaurant_leader_report".
    source: str

    @classmethod
    def of(cls, link: ContactLink) -> ContactRead:
        c = link.contact
        return cls(
            id=link.id,
            contact_id=c.id,
            role=link.role,
            name=c.name,
            email=c.email,
            phone=c.phone,
            source=link.source,
        )
