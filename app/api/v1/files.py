import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.v1._file_response import file_response
from app.db.session import get_db
from app.models import StoredFile
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{file_id}", response_class=Response)
def get_file(
    file_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    """A stored file, for callers holding `files:read` for its company: an operator or platform
    grant covers every company beneath it, a company grant only its own company. A file with
    no company yet needs the operator-level permission. Others get 404."""
    stored = db.get(StoredFile, file_id)
    if stored is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    scope.require(
        Perm.files_read,
        stored.operator_id,
        read_perm=Perm.files_read,
        company_id=stored.company_id,
    )
    return file_response(
        stored.storage_key, stored.content_type, stored.original_name, f"file-{stored.id}"
    )
