from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.search import SearchResults
from app.security.access import AccessScope, require_any
from app.security.permissions import Perm
from app.services import search as search_service

router = APIRouter(tags=["search"])


@router.get("/search", response_model=SearchResults)
def search(
    q: str = Query(min_length=2, max_length=100),
    limit: int = Query(default=5, ge=1, le=10),
    db: Session = Depends(get_db),
    scope: AccessScope = Depends(require_any(Perm.operators_read)),
):
    """Operators, companies, bill-tos, locations, service orders, and invoices matching `q`,
    limited to what the caller can open. Names match anywhere; ids and numbers match exactly."""
    return SearchResults(query=q, items=search_service.search(db, scope, q, limit=limit))
