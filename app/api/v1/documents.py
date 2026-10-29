import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.v1._file_response import file_response
from app.db.session import get_db
from app.models import Document
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm

router = APIRouter(prefix="/documents", tags=["documents"])


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
    return file_response(
        document.storage_key,
        document.content_type,
        document.file_name,
        f"document-{document.pestpac_document_id}",
    )
