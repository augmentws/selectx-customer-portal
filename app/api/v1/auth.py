from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.models import AuthSession, Membership, Role, Tenant, User
from app.schemas.auth import (
    LoginRequest,
    MembershipGrant,
    MeRead,
    PasswordChange,
    RefreshRequest,
    TokenPair,
)
from app.security.deps import get_current_session, get_current_user
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenPair)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    try:
        return auth_service.login(db, email=data.email, password=data.password)
    except auth_service.LoginLockedError as exc:
        minutes = -(-exc.retry_after // 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed sign-ins. Try again in {minutes} "
            f"minute{'s' if minutes != 1 else ''}.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from None
    except auth_service.AuthError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        ) from None


@router.post("/refresh", response_model=TokenPair)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)):
    try:
        return auth_service.refresh(db, data.refresh_token)
    except auth_service.AuthError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        ) from None


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(session: AuthSession = Depends(get_current_session), db: Session = Depends(get_db)):
    auth_service.logout(db, session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    data: PasswordChange,
    user: User = Depends(get_current_user),
    session: AuthSession = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    try:
        auth_service.change_password(
            db,
            user=user,
            session=session,
            current_password=data.current_password,
            new_password=data.new_password,
        )
    except auth_service.PasswordReuseError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must differ from the current one",
        ) from None
    except auth_service.AuthError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect"
        ) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeRead)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Membership, Tenant)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(Membership.user_id == user.id, Tenant.is_active.is_(True))
        .options(selectinload(Membership.role).selectinload(Role.permissions))
        .order_by(Tenant.kind, Tenant.name)
    ).all()
    return MeRead(
        id=user.id,
        email=user.email,
        must_change_password=bool(user.credential and user.credential.must_change_password),
        memberships=[
            MembershipGrant(
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                tenant_kind=tenant.kind,
                role=m.role.name,
                permissions=sorted(p.code for p in m.role.permissions),
            )
            for m, tenant in rows
        ],
    )
