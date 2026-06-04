import hashlib
import uuid
from datetime import timedelta

import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_and_update,
    verify_password,
)
from app.db.redis import RedisKeys
from app.models.user import User
from app.schemas.auth import TokenResponse
from app.schemas.user import UserCreate, UserRead

settings = get_settings()

class AuthError(Exception):
    """
    Domain-level auth error. Raised by the service, caught by the router.
    The router converts this to HTTPException with the right status code.
    This keeps HTTP concerns OUT of the service layer.
    """
    def __init__(self, message: str, code: str = "auth_error"):
        self.message = message
        self.code = code
        super().__init__(message)


class AuthService:
    """
    Handles registration, login, token refresh, and logout.
    """

    def __init__(self, db: AsyncSession, redis: aioredis.Redis):
        self.db = db
        self.redis = redis

    # -----------------------------------------------------------------------
    # Registration
    # -----------------------------------------------------------------------
    async def register(self, payload: UserCreate) -> UserRead:
        """
        Create a new user.
        Raises AuthError if  email already exists.
        """
        # Check for duplicate username
        existing = await self.db.execute(
            select(User).where(
                (User.username == payload.username) | (User.email == payload.email)
            )
        )
        if existing.scalar_one_or_none():
            raise AuthError(
                "Email or username already registered.",
                code="duplicate_user",
            )

        user = User(
            username=payload.username,
            email=payload.email,
            hashed_password=hash_password(payload.password),
            is_active=True,
            is_verified=False,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return UserRead.model_validate(user)

    # -----------------------------------------------------------------------
    # Login
    # -----------------------------------------------------------------------
    async def login(self, username: str, password: str) -> TokenResponse:
        """
        Authenticate user and issue access + refresh tokens.
        """
        user = await self._get_user_by_username(username)

        DUMMY = "$2b$12$KIXjJ2MNpxqJiBjF5BaGpe"  # A valid bcrypt hash for timing.
        password_to_check = user.hashed_password if user else DUMMY

        if not user or not verify_password(password, password_to_check):
            raise AuthError("Incorrect username or password.", code="invalid_credentials")

        if not user.is_active:
            raise AuthError("Account is disabled.", code="inactive_user")

        is_valid, new_hash = verify_and_update(password, password_to_check)

        if not user or not is_valid:
            raise AuthError("Incorrect username or password.", code="invalid_credentials")

        # Silently rehash if algorithm was upgraded
        if new_hash:
            user.hashed_password = new_hash
            await self.db.commit()

        return await self._issue_tokens(user)

    # -----------------------------------------------------------------------
    # Token refresh
    # -----------------------------------------------------------------------
    async def refresh(self, refresh_token: str) -> TokenResponse:
        """
        Validate a refresh token and issue a new token pair.
        Implements refresh token rotation: old refresh token is revoked,
        new one is issued. If a rotated token is reused → revoke all sessions.
        """
        from jose import JWTError
        from app.core.security import decode_token

        try:
            payload = decode_token(refresh_token)
        except JWTError:
            raise AuthError("Invalid or expired refresh token.", code="invalid_token")

        if payload.get("type") != "refresh":
            raise AuthError("Token type mismatch.", code="invalid_token")

        jti: str = payload["jti"]
        user_id: str = payload["sub"]

        # Check blacklist
        if await self.redis.get(RedisKeys.blacklist(jti)):
            # Reuse of a revoked refresh token — possible token theft.
            # Revoke ALL sessions for this user as a precaution.
            await self._revoke_all_sessions(user_id)
            raise AuthError(
                "Refresh token already used. All sessions revoked.",
                code="token_reuse",
            )

        user = await self._get_user_by_id(uuid.UUID(user_id))
        if not user or not user.is_active:
            raise AuthError("User not found or inactive.", code="invalid_credentials")

        # Blacklist the used refresh token
        remaining_ttl = int(
            timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS).total_seconds()
        )
        await self.redis.setex(RedisKeys.blacklist(jti), remaining_ttl, "1")

        return await self._issue_tokens(user)

    # -----------------------------------------------------------------------
    # Logout
    # -----------------------------------------------------------------------
    async def logout(self, access_jti: str, refresh_token: str | None = None) -> None:
        """
        Blacklist the current access token (and refresh token if provided).
        After this, both tokens are rejected by get_current_user.
        """
        access_ttl = int(
            timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES).total_seconds()
        )
        await self.redis.setex(RedisKeys.blacklist(access_jti), access_ttl, "1")

        if refresh_token:
            from jose import JWTError
            from app.core.security import decode_token
            try:
                payload = decode_token(refresh_token)
                refresh_jti = payload.get("jti")
                if refresh_jti:
                    refresh_ttl = int(
                        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS).total_seconds()
                    )
                    await self.redis.setex(
                        RedisKeys.blacklist(refresh_jti), refresh_ttl, "1"
                    )
            except JWTError:
                pass  # Expired refresh token on logout is fine — already invalid.

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------
    async def _issue_tokens(self, user: User) -> TokenResponse:
        """Create and return a new access + refresh token pair."""
        subject = str(user.id)
        access_token, _ = create_access_token(subject)
        refresh_token, _ = create_refresh_token(subject)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def _get_user_by_username(self, username: str) -> User | None:
        result = await self.db.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def _get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()

    async def _revoke_all_sessions(self, user_id: str) -> None:
        """Nuclear option: called on suspected token theft."""
        # A simple implementation: set a per-user revocation timestamp in Redis.
        # Any token issued before this timestamp is invalid.
        # A more thorough approach uses a user-level version counter.
        await self.redis.set(
            f"revoke_all:{user_id}",
            str(int(__import__("time").time())),
            ex=int(timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS).total_seconds()),
        )