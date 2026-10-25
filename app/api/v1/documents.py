import re
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Document
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm
from app.storage import StorageError, StorageNotConfiguredError, get_storage

router = APIRouter(prefix="/documents", tags=["documents"])

# Shown in the browser; anything else (HTML, SVG, ...) is a download, so a file from PestPac
# can never run script on our origin.
INLINE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "application/pdf"}


def _disposition(kind: str, file_name: str | None, fallback: str) -> str:
    name = file_name or fallback
    ascii_name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip() or fallback
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


@router.get("/{document_id}/file", response_class=Response)
def get_document_file(
    document_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """The document's stored file. Images and PDFs are shown inline; other types download."""
    document = db.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    scope.require(Perm.bill_tos_read, document.operator_id, read_perm=Perm.bill_tos_read)
    if document.storage_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not stored yet")
    try:
        stored = get_storage().get(document.storage_key)
    except StorageNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except StorageError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    content_type = document.content_type or stored.content_type
    kind = "inline" if content_type in INLINE_TYPES else "attachment"
    headers = {
        "Content-Disposition": _disposition(
            kind, document.file_name, f"document-{document.pestpac_document_id}"
        ),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-cache",
    }
    # Chrome's PDF viewer won't load in a sandboxed document (ERR_BLOCKED_BY_CLIENT). A PDF
    # is still pinned to application/pdf by nosniff and renders in the browser's own viewer.
    if content_type != "application/pdf":
        headers["Content-Security-Policy"] = "sandbox"
    return Response(
        stored.data,
        media_type=content_type if kind == "inline" else "application/octet-stream",
        headers=headers,
    )
