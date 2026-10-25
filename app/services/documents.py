"""PestPac documents for a location: metadata in `documents`, files in object storage.

1. GET /Locations/{id}/documents?startDate=...&includeConditionDocuments=true lists them (not
   paged; documents, forms, call and condition documents; not company documents).
2. GET /Documents/{id}/download?type={DocumentType} returns a file. Files are fetched once
   and never re-fetched: a stored document's file doesn't change.
"""

import hashlib
import mimetypes
import uuid
from datetime import UTC, datetime, time

import requests
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.pestpac import PestPacAuthError, PestPacClient
from app.models import Document, Location, ServiceOrder
from app.schemas.pestpac import DocumentSyncCounts, PestPacDocument
from app.services.pestpac_connection import PestPacUnavailableError
from app.storage import ObjectStorage


class DocumentFileError(RuntimeError):
    """One file couldn't be fetched (PestPac refused it or sent something else). Recorded on
    the document; the sync carries on with the next one."""


def _get(client: PestPacClient, path: str, params: dict, accept: str) -> requests.Response:
    try:
        return client.custom_endpoint(path).get(params=params, accept=accept)
    except (PestPacAuthError, requests.RequestException) as exc:
        raise PestPacUnavailableError(f"Could not reach PestPac: {type(exc).__name__}") from exc


def fetch_location_documents(
    client: PestPacClient, pestpac_location_id: int
) -> list[PestPacDocument]:
    start = get_settings().pestpac_documents_start_date
    response = _get(
        client,
        f"/Locations/{pestpac_location_id}/documents",
        {"startDate": start.isoformat(), "includeConditionDocuments": "true"},
        "application/json",
    )
    if response.status_code != 200:
        raise PestPacUnavailableError(
            f"PestPac /Locations/{pestpac_location_id}/documents returned {response.status_code}"
        )
    try:
        body = response.json()
    except ValueError:
        body = None
    if not isinstance(body, list) or not all(
        isinstance(d, dict) and "DocumentID" in d and "DocumentType" in d for d in body
    ):
        raise PestPacUnavailableError("PestPac returned an unexpected documents response")
    return [PestPacDocument.from_api(d) for d in body]


def download_file(client: PestPacClient, document: Document) -> tuple[bytes, str]:
    """The document's file and its content type."""
    response = _get(
        client,
        f"/Documents/{document.pestpac_document_id}/download",
        {"type": document.document_type},
        "*/*",
    )
    if response.status_code != 200:
        raise DocumentFileError(f"PestPac download returned {response.status_code}")
    content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    # An error or metadata object instead of the file; don't store it as the document.
    if content_type in {"application/json", "text/json"}:
        raise DocumentFileError("PestPac sent JSON instead of the file")
    if not content_type or content_type == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(document.file_name or "")
        content_type = guessed or "application/octet-stream"
    return response.content, content_type


def storage_key(document: Document) -> str:
    # By id, not file name: PestPac file names repeat and contain spaces and punctuation.
    return (
        f"operators/{document.operator_id}/documents/"
        f"{document.document_type}/{document.pestpac_document_id}"
    )


def _apply(
    db: Session, document: Document, listed: PestPacDocument, location: Location, now: datetime
) -> None:
    for field, value in listed.model_dump().items():
        setattr(document, field, value)
    # Listed under this location, so it's this location's document.
    document.location_id = location.id
    document.pestpac_location_id = location.pestpac_location_id
    document.service_order_id = (
        db.scalar(
            select(ServiceOrder.id).where(
                ServiceOrder.operator_id == document.operator_id,
                ServiceOrder.pestpac_order_id == listed.pestpac_order_id,
            )
        )
        if listed.pestpac_order_id is not None
        else None
    )
    document.removed_at = None
    document.pestpac_fetched_at = now


def upsert_documents(
    db: Session, location: Location, items: list[PestPacDocument], now: datetime
) -> list[tuple[Document, bool]]:
    """Insert or update listed documents for the location; each with whether it's new. Does
    not commit."""
    existing = {
        (d.document_type, d.pestpac_document_id): d
        for d in db.scalars(
            select(Document).where(
                Document.operator_id == location.operator_id,
                Document.pestpac_document_id.in_([d.pestpac_document_id for d in items]),
            )
        )
    }
    result: list[tuple[Document, bool]] = []
    for item in items:
        document = existing.get((item.document_type, item.pestpac_document_id))
        created = document is None
        if document is None:
            document = Document(
                operator_id=location.operator_id,
                document_type=item.document_type,
                pestpac_document_id=item.pestpac_document_id,
            )
            db.add(document)
            existing[(item.document_type, item.pestpac_document_id)] = document
        _apply(db, document, item, location, now)
        result.append((document, created))
    return result


def sync_location_metadata(
    db: Session, client: PestPacClient, location: Location, counts: DocumentSyncCounts
) -> None:
    """Upsert the location's listed documents and mark ones it no longer lists. Does not
    commit."""
    listed = fetch_location_documents(client, location.pestpac_location_id)
    now = datetime.now(UTC)
    counts.total += len(listed)
    keys = {(d.document_type, d.pestpac_document_id) for d in listed}
    for _, created in upsert_documents(db, location, listed, now):
        if created:
            counts.added += 1
        else:
            counts.updated += 1

    # The list only covers documents from the start date on, so only those can be "removed".
    # A condition's documents are kept by the condition sync, whatever this list says.
    start = datetime.combine(get_settings().pestpac_documents_start_date, time())
    for document in db.scalars(
        select(Document).where(
            Document.location_id == location.id,
            Document.removed_at.is_(None),
            Document.condition_id.is_(None),
            Document.document_date >= start,
        )
    ):
        if (document.document_type, document.pestpac_document_id) not in keys:
            document.removed_at = now
            counts.removed += 1
    db.flush()


def store_location_files(
    db: Session,
    client: PestPacClient,
    storage: ObjectStorage,
    location: Location,
    counts: DocumentSyncCounts,
) -> None:
    """Download and store files not stored yet, committing after each one so progress
    survives a later failure. A file's own problem is recorded on it; PestPac or storage
    being unreachable (PestPacUnavailableError, StorageError) stops the location."""
    max_bytes = get_settings().document_max_bytes
    pending = db.scalars(
        select(Document)
        .where(
            Document.location_id == location.id,
            Document.removed_at.is_(None),
            Document.storage_key.is_(None),
            # Known to be too large: don't download again until the limit is raised.
            or_(Document.size_bytes.is_(None), Document.size_bytes <= max_bytes),
        )
        .order_by(Document.document_date.desc().nulls_last(), Document.id)
    ).all()
    for document in pending:
        document.file_attempts += 1
        try:
            data, content_type = download_file(client, document)
        except DocumentFileError as exc:
            document.file_error = str(exc)[:500]
            counts.files_failed += 1
            db.commit()
            continue
        if len(data) > max_bytes:
            document.size_bytes = len(data)
            document.file_error = f"Larger than the {max_bytes:,}-byte limit"
            counts.files_too_large += 1
            db.commit()
            continue
        key = storage_key(document)
        storage.put(key, data, content_type)
        document.storage_key = key
        document.content_type = content_type[:200]
        document.size_bytes = len(data)
        document.sha256 = hashlib.sha256(data).hexdigest()
        document.file_stored_at = datetime.now(UTC)
        document.file_error = None
        counts.files_stored += 1
        db.commit()


def list_documents(db: Session, *, location_id: uuid.UUID) -> list[Document]:
    """The location's current documents, newest first."""
    return list(
        db.scalars(
            select(Document)
            .where(Document.location_id == location_id, Document.removed_at.is_(None))
            .order_by(Document.document_date.desc().nulls_last(), Document.id)
        )
    )
