import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AuthSession, Credential, LoginThrottle, User
from app.schemas.auth import TokenPair
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.security.tokens import TokenError, create_token, decode_token


class AuthError(Exception):
    pass


class PasswordReuseError(AuthError):
    pass


class LoginLockedError(AuthError):
    """Too many failed sign-ins for this email; `retry_after` is in seconds."""

    def __init__(self, retry_after: int):
        super().__init__("too many failed sign-ins")
        self.retry_after = retry_after


def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_user(
    db: Session, *, email: str, password: str, must_change_password: bool = False
) -> User:
    """Adds a user with credentials. Does not commit, so callers can add memberships atomically."""
    user = User(email=normalize_email(email))
    user.credential = Credential(
        password_hash=hash_password(password), must_change_password=must_change_password
    )
    db.add(user)
    db.flush()
    return user


def change_password(
    db: Session, *, user: User, session: AuthSession, current_password: str, new_password: str
) -> None:
    """Sets a new password, clears the temporary-password flag, and signs out other sessions."""
    if user.credential is None or not verify_password(
        user.credential.password_hash, current_password
    ):
        raise AuthError("invalid credentials")
    if verify_password(user.credential.password_hash, new_password):
        raise PasswordReuseError("new password must differ")
    user.credential.password_hash = hash_password(new_password)
    user.credential.must_change_password = False
    now = datetime.now(UTC)
    for other in db.scalars(
        select(AuthSession).where(
            AuthSession.user_id == user.id,
            AuthSession.id != session.id,
            AuthSession.revoked_at.is_(None),
        )
    ):
        other.revoked_at = now
    db.commit()


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


def _record_failure(db: Session, email: str, now: datetime) -> None:
    """Count a failed sign-in for the email, locking it once the window holds too many.
    Commits. An upsert, so concurrent failures for the same email all count."""
    settings = get_settings()
    stale = LoginThrottle.first_failed_at < now - timedelta(
        minutes=settings.login_failure_window_minutes
    )
    failures = db.execute(
        pg_insert(LoginThrottle)
        .values(email=email, failures=1, first_failed_at=now)
        .on_conflict_do_update(
            index_elements=[LoginThrottle.email],
            set_={
                "failures": case((stale, 1), else_=LoginThrottle.failures + 1),
                "first_failed_at": case((stale, now), else_=LoginThrottle.first_failed_at),
            },
        )
        .returning(LoginThrottle.failures)
    ).scalar_one()
    if failures >= settings.login_max_failures:
        db.execute(
            update(LoginThrottle)
            .where(LoginThrottle.email == email)
            .values(
                failures=0,
                first_failed_at=now,
                locked_until=now + timedelta(minutes=settings.login_lock_minutes),
            )
        )
    db.commit()


def login(db: Session, *, email: str, password: str) -> TokenPair:
    """Raises LoginLockedError (before checking the password) while the email is locked, and
    AuthError for wrong credentials, counted towards a lockout."""
    key = normalize_email(email)
    now = datetime.now(UTC)
    throttle = db.get(LoginThrottle, key)
    if throttle is not None and throttle.locked_until is not None and throttle.locked_until > now:
        raise LoginLockedError(int((throttle.locked_until - now).total_seconds()) + 1)

    user = get_user_by_email(db, email)
    if user is None or not user.is_active or user.credential is None:
        # Hash anyway so response time doesn't reveal whether the email exists.
        hash_password(password)
        _record_failure(db, key, now)
        raise AuthError("invalid credentials")
    if not verify_password(user.credential.password_hash, password):
        _record_failure(db, key, now)
        raise AuthError("invalid credentials")
    db.execute(delete(LoginThrottle).where(LoginThrottle.email == key))
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
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        # Deactivated: end the session rather than keep issuing tokens it can't use.
        session.revoked_at = datetime.now(UTC)
        db.commit()
        raise AuthError("user inactive")
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
