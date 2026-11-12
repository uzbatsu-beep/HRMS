"""Local authentication and an initial administrator-managed user directory."""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.identity.models import LoginSession, UserAccount
from app.identity.schemas import LoginRequest, LoginResult, SessionResult, UserCreate, UserView
from app.identity.security import (
    COOKIE_NAME,
    SESSION_HOURS,
    get_authenticated_session,
    get_current_user,
    hash_password,
    hash_session_token,
    normalize_username,
    require_admin,
    require_csrf,
    verify_password,
)

router = APIRouter(prefix=f"{settings.api_v1_prefix}/auth", tags=["identity"])


@router.post("/login", response_model=LoginResult)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),  # noqa: B008
) -> LoginResult:
    """Create a revocable opaque session; no user or password data is stored in cookies."""

    origin = request.headers.get("origin")
    if origin is not None and origin not in settings.cors_origins:
        raise HTTPException(status_code=403, detail="Origin not allowed")

    user = db.scalar(
        select(UserAccount).where(UserAccount.username == normalize_username(payload.username))
    )
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    raw_token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    record = LoginSession(
        user_id=user.id,
        token_hash=hash_session_token(raw_token),
        csrf_token=csrf_token,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS),
    )
    db.add(record)
    db.commit()

    response.set_cookie(
        key=COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=settings.app_env not in {"development", "test"},
        samesite="strict",
        max_age=SESSION_HOURS * 3600,
        path="/",
    )
    return LoginResult(user=UserView.model_validate(user), csrf_token=csrf_token)


@router.get("/me", response_model=SessionResult)
def me(
    record: LoginSession = Depends(get_authenticated_session),  # noqa: B008
    user: UserAccount = Depends(get_current_user),  # noqa: B008
) -> SessionResult:
    """Allow same-origin clients to recover an anti-CSRF token after a page reload."""

    return SessionResult(user=UserView.model_validate(user), csrf_token=record.csrf_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
def logout(
    response: Response,
    record: LoginSession = Depends(get_authenticated_session),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> None:
    record.revoked_at = datetime.now(timezone.utc)
    db.commit()
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=settings.app_env not in {"development", "test"},
        samesite="strict",
        httponly=True,
    )


@router.get("/users", response_model=list[UserView])
def list_users(
    _admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[UserAccount]:
    return list(db.scalars(select(UserAccount).order_by(UserAccount.username)).all())


@router.post(
    "/users",
    response_model=UserView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_user(
    payload: UserCreate,
    _admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> UserAccount:
    username = normalize_username(payload.username)
    account = UserAccount(
        username=username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(account)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Username already exists") from exc
    db.refresh(account)
    return account
