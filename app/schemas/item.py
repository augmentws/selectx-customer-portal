import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.item import ItemStatus


class ItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: ItemStatus
    created_at: datetime
