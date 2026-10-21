import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Item
from app.schemas.item import ItemCreate


def list_items(db: Session) -> list[Item]:
    return list(db.scalars(select(Item).order_by(Item.created_at.desc())))


def get_item(db: Session, item_id: uuid.UUID) -> Item | None:
    return db.get(Item, item_id)


def create_item(db: Session, data: ItemCreate) -> Item:
    item = Item(name=data.name)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item
