import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import BillTo, Location
from app.schemas.contacts import ContactRead
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.services import contacts

router = APIRouter(tags=["contacts"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.get("/locations/{location_id}/contacts", response_model=list[ContactRead])
def list_location_contacts(
    location_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """The location's contacts: the store's own phone and email first, then its leaders from
    the top down. Visible to anyone who can see the location."""
    location = db.get(Location, location_id)
    if location is None:
        raise _not_found()
    scope.require(Perm.bill_tos_read, location.operator_id, read_perm=Perm.bill_tos_read)
    return [ContactRead.of(link) for link in contacts.list_for_location(db, location.id)]


@router.get("/bill-tos/{bill_to_id}/contacts", response_model=list[ContactRead])
def list_bill_to_contacts(
    bill_to_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """Contacts linked to the bill-to itself (not its locations'). Visible to anyone who can see
    the bill-to."""
    bill_to = db.get(BillTo, bill_to_id)
    if bill_to is None:
        raise _not_found()
    scope.require(Perm.bill_tos_read, bill_to.operator_id, read_perm=Perm.bill_tos_read)
    return [ContactRead.of(link) for link in contacts.list_for_bill_to(db, bill_to.id)]
