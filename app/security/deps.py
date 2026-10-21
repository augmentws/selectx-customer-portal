import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import AuthSession, User
from app.security.tokens import TokenError, decode_token

_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_session(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AuthSession:
    if creds is None:
        raise _UNAUTHORIZED
    try:
        payload = decode_token(creds.credentials, "access")
        session_id = uuid.UUID(payload["sid"])
    except TokenError, KeyError, ValueError:
        raise _UNAUTHORIZED from None
    session = db.scalar(select(AuthSession).where(AuthSession.id == session_id))
    if session is None or session.revoked_at is not None:
        raise _UNAUTHORIZED
    return session


def get_current_user(
    session: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required")
    return user
