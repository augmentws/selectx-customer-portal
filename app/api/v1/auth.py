from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import AuthSession, User
from app.schemas.auth import LoginRequest, RefreshRequest, TokenPair, UserRead
from app.security.deps import get_current_session, get_current_user
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenPair)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    try:
        return auth_service.login(db, email=data.email, password=data.password)
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


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)):
    return user
