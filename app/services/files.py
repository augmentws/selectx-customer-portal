"""Stored files: one `stored_files` row per object in object storage.

Whatever stores a file goes through `store_file`, which writes the object and its row together;
the owning record keeps the returned file's id. Each file carries its operator and, once known,
its company, which is what GET /v1/files/{id} checks access against.
"""

import hashlib
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import BillTo, Location, StoredFile
from app.storage import ObjectStorage


def store_file(
    db: Session,
    storage: ObjectStorage,
    *,
    operator_id: uuid.UUID,
    company_id: uuid.UUID | None,
    source: str,
    key: str,
    data: bytes,
    content_type: str,
    original_name: str | None = None,
) -> StoredFile:
    """Write the object, then record it. Writing to a key that already has a row (a file
    fetched again) replaces the object and updates that row. Flushes; the caller commits."""
    storage.put(key, data, content_type)
    stored = db.scalar(select(StoredFile).where(StoredFile.storage_key == key))
    if stored is None:
        stored = StoredFile(operator_id=operator_id, storage_key=key)
        db.add(stored)
    stored.company_id = company_id
    stored.source = source
    stored.content_type = content_type[:100]
    stored.size_bytes = len(data)
    stored.sha256 = hashlib.sha256(data).hexdigest()
    stored.original_name = (original_name or "")[:300] or None
    db.flush()
    return stored


def company_for_location(db: Session, location_id: uuid.UUID | None) -> uuid.UUID | None:
    if location_id is None:
        return None
    return db.scalar(
        select(BillTo.company_id)
        .join(Location, Location.bill_to_id == BillTo.id)
        .where(Location.id == location_id)
    )


def set_company(db: Session, file_ids: list[uuid.UUID], company_id: uuid.UUID | None) -> None:
    """Re-point files at a company (their owner was linked to a different location)."""
    if file_ids:
        db.execute(
            update(StoredFile).where(StoredFile.id.in_(file_ids)).values(company_id=company_id)
        )
