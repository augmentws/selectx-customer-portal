import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import SyncJob
from app.schemas.tenancy import SyncJobRead
from app.security.access import AccessScope, get_scope
from app.security.permissions import Perm

router = APIRouter(prefix="/sync-jobs", tags=["sync_jobs"])


@router.get("/{job_id}", response_model=SyncJobRead)
def get_sync_job(
    job_id: uuid.UUID, db: Session = Depends(get_db), scope: AccessScope = Depends(get_scope)
):
    job = db.get(SyncJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    scope.require(Perm.bill_tos_read, job.operator_id, read_perm=Perm.bill_tos_read)
    return job
