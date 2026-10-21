import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import User
from app.schemas.item import ItemCreate, ItemRead
from app.security.deps import get_current_user
from app.services import items as items_service

router = APIRouter(prefix="/items", tags=["items"])


@router.get("", response_model=list[ItemRead])
def list_items(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return items_service.list_items(db)


@router.post("", response_model=ItemRead, status_code=status.HTTP_201_CREATED)
def create_item(
    data: ItemCreate, db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    return items_service.create_item(db, data)


@router.get("/{item_id}", response_model=ItemRead)
def get_item(
    item_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    item = items_service.get_item(db, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item not found")
    return item
