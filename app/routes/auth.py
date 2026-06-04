from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer

from app.core.security import decode_token
from app.dependencies.auth import CurrentUser, DbSession, RedisClient
from app.schemas.auth import MessageResponse, RefreshRequest, TokenResponse
from app.schemas.user import UserCreate, UserRead
from app.services.auth import AuthError, AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])

# ---------------------------------------------------------------------------
# Helper: service factory (keeps routes DRY)
# ---------------------------------------------------------------------------
# We don't inject AuthService via Depends directly because it needs
# both db and redis. This factory wires them together cleanly.
def get_auth_service(db: DbSession, redis: RedisClient) -> AuthService:
    return AuthService(db=db, redis=redis)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# ---------------------------------------------------------------------------
# Error translator
# ---------------------------------------------------------------------------
# Maps domain error codes → HTTP status codes.
# ONE place to change if you want different status codes.
_AUTH_ERROR_STATUS = {
    "duplicate_user":       status.HTTP_409_CONFLICT,
    "invalid_credentials":  status.HTTP_401_UNAUTHORIZED,
    "inactive_user":        status.HTTP_403_FORBIDDEN,
    "invalid_token":        status.HTTP_401_UNAUTHORIZED,
    "token_reuse":          status.HTTP_401_UNAUTHORIZED,
}

def _raise_http(error: AuthError) -> None:
    status_code = _AUTH_ERROR_STATUS.get(error.code, status.HTTP_400_BAD_REQUEST)
    raise HTTPException(status_code=status_code, detail=error.message)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(payload: UserCreate, svc: AuthServiceDep) -> UserRead:
    try:
        return await svc.register(payload)
    except AuthError as e:
        _raise_http(e)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login and receive access + refresh tokens",
)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    svc: AuthServiceDep,
) -> TokenResponse:
    """
    Uses OAuth2PasswordRequestForm so the /docs 'Authorize' button works.
    form_data.username can be a username or email — the service handles both.
    """
    try:
        return await svc.login(form_data.username, form_data.password)
    except AuthError as e:
        _raise_http(e)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Exchange a refresh token for a new token pair",
)
async def refresh(payload: RefreshRequest, svc: AuthServiceDep) -> TokenResponse:
    try:
        return await svc.refresh(payload.refresh_token)
    except AuthError as e:
        _raise_http(e)


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Revoke current access token (and optionally refresh token)",
)
async def logout(
    current_user: CurrentUser,        # Validates the access token first.
    svc: AuthServiceDep,
    token: Annotated[str, Depends(oauth2_scheme)], 
    payload: RefreshRequest | None = None,
) -> MessageResponse:
    token_payload = decode_token(token)
    access_jti: str = token_payload["jti"]

    await svc.logout(
        access_jti=access_jti,
        refresh_token=payload.refresh_token if payload else None,
    )

    return MessageResponse(message="Successfully logged out.")


@router.get(
    "/me",
    response_model=UserRead,
    summary="Get the currently authenticated user",
)
async def get_me(current_user: CurrentUser) -> UserRead:
    return UserRead.model_validate(current_user)