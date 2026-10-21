import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AuthSession, Credential, User
from app.schemas.auth import TokenPair
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.security.tokens import TokenError, create_token, decode_token


class AuthError(Exception):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_user(db: Session, *, email: str, password: str, is_admin: bool = False) -> User:
    user = User(email=normalize_email(email), is_admin=is_admin)
    user.credential = Credential(password_hash=hash_password(password))
    db.add(user)
    db.commit()
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == normalize_email(email)))


def _issue(session: AuthSession) -> TokenPair:
    settings = get_settings()
    access_ttl = timedelta(minutes=settings.access_token_ttl_minutes)
    jti = uuid.uuid4()
    session.current_jti = jti
    access = create_token(
        subject=session.user_id, token_type="access", ttl=access_ttl, extra={"sid": str(session.id)}
    )
    refresh = create_token(
        subject=session.user_id,
        token_type="refresh",
        ttl=session.expires_at - datetime.now(UTC),
        extra={"sid": str(session.id), "jti": str(jti)},
    )
    return TokenPair(
        access_token=access, refresh_token=refresh, expires_in=int(access_ttl.total_seconds())
    )


def login(db: Session, *, email: str, password: str) -> TokenPair:
    user = get_user_by_email(db, email)
    if user is None or not user.is_active or user.credential is None:
        # Hash anyway so response time doesn't reveal whether the email exists.
        hash_password(password)
        raise AuthError("invalid credentials")
    if not verify_password(user.credential.password_hash, password):
        raise AuthError("invalid credentials")
    if needs_rehash(user.credential.password_hash):
        user.credential.password_hash = hash_password(password)

    settings = get_settings()
    session = AuthSession(
        id=uuid.uuid4(),
        user_id=user.id,
        current_jti=uuid.uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_ttl_days),
    )
    db.add(session)
    tokens = _issue(session)
    db.commit()
    return tokens


def refresh(db: Session, refresh_token: str) -> TokenPair:
    try:
        payload = decode_token(refresh_token, "refresh")
        session_id = uuid.UUID(payload["sid"])
        jti = uuid.UUID(payload["jti"])
    except (TokenError, KeyError, ValueError) as exc:
        raise AuthError("invalid refresh token") from exc

    session = db.scalar(select(AuthSession).where(AuthSession.id == session_id).with_for_update())
    if session is None or session.revoked_at is not None:
        raise AuthError("session revoked")
    if session.current_jti != jti:
        # An already-rotated token was replayed: treat the family as compromised.
        session.revoked_at = datetime.now(UTC)
        db.commit()
        raise AuthError("refresh token reuse detected")

    tokens = _issue(session)
    db.commit()
    return tokens


def logout(db: Session, session: AuthSession) -> None:
    if session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
        db.commit()
