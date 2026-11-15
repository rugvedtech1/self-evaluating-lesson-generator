"""Authentication routes. Supabase Auth checks passwords; we never store them."""

import logging

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import AuthClient, BearerToken, CurrentUser, DbSession
from app.core.exceptions import AuthRejectedError, AuthServiceUnavailableError
from app.schemas.auth import (
    LoginRequest, MeResponse, RefreshRequest, SessionResponse, SignupRequest, SignupResponse, UserInfo,
)
from app.services.profiles import ensure_profile
from app.services.supabase_auth import AuthSession, AuthUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _user_info(user: AuthUser) -> UserInfo:
    return UserInfo(id=user.id, email=user.email)


def _session_response(session: AuthSession) -> SessionResponse:
    return SessionResponse(
        access_token=session.access_token,
        refresh_token=session.refresh_token,
        expires_in=session.expires_in,
        token_type=session.token_type,
        user=_user_info(session.user),
    )


def _rejected(exc: AuthRejectedError, default_status: int) -> HTTPException:
    code = status.HTTP_429_TOO_MANY_REQUESTS if exc.status_code == 429 else default_status
    return HTTPException(status_code=code, detail=str(exc))


def _unavailable(exc: AuthServiceUnavailableError) -> HTTPException:
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, auth: AuthClient, db: DbSession) -> SignupResponse:
    try:
        result = auth.sign_up(body.email, body.password.get_secret_value())
    except AuthRejectedError as exc:
        raise _rejected(exc, status.HTTP_400_BAD_REQUEST) from exc
    except AuthServiceUnavailableError as exc:
        raise _unavailable(exc) from exc

    ensure_profile(db, result.user.id, result.user.email or body.email)
    logger.info("User signed up", extra={"context": {"user_id": str(result.user.id)}})
    return SignupResponse(
        user=_user_info(result.user),
        session=_session_response(result.session) if result.session else None,
        email_confirmation_required=result.session is None,
    )


@router.post("/login", response_model=SessionResponse)
def login(body: LoginRequest, auth: AuthClient, db: DbSession) -> SessionResponse:
    try:
        session = auth.sign_in_with_password(body.email, body.password.get_secret_value())
    except AuthRejectedError as exc:
        raise _rejected(exc, status.HTTP_401_UNAUTHORIZED) from exc
    except AuthServiceUnavailableError as exc:
        raise _unavailable(exc) from exc

    ensure_profile(db, session.user.id, session.user.email or body.email)
    logger.info("User logged in", extra={"context": {"user_id": str(session.user.id)}})
    return _session_response(session)


@router.post("/refresh", response_model=SessionResponse)
def refresh(body: RefreshRequest, auth: AuthClient) -> SessionResponse:
    try:
        return _session_response(auth.refresh_session(body.refresh_token))
    except AuthRejectedError as exc:
        raise _rejected(exc, status.HTTP_401_UNAUTHORIZED) from exc
    except AuthServiceUnavailableError as exc:
        raise _unavailable(exc) from exc


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(user: CurrentUser, token: BearerToken, auth: AuthClient) -> Response:
    try:
        auth.sign_out(token)
    except AuthRejectedError:
        pass  # session already ended on Supabase's side: the user is logged out either way
    except AuthServiceUnavailableError as exc:
        raise _unavailable(exc) from exc
    logger.info("User logged out", extra={"context": {"user_id": str(user.id)}})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeResponse)
def me(user: CurrentUser, db: DbSession) -> MeResponse:
    profile = ensure_profile(db, user.id, user.email)
    return MeResponse(id=profile.id, email=profile.email, display_name=profile.display_name)
