import uuid
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.redis import RedisKeys, get_redis
from app.db.sessions import get_db
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
DbSession = Annotated[AsyncSession, Depends(get_db)]
RedisClient = Annotated[aioredis.Redis, Depends(get_redis)]


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DbSession,
    redis: RedisClient,
) -> User:
    """
    Decode the JWT, check the blacklist, return the User ORM object.
    Raises HTTP 401 on any failure 
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # 1. Decode & validate JWT signature + expiry
    try:
        payload = decode_token(token)
    except JWTError:
        raise credentials_exception

    # 2. Reject refresh tokens used as access tokens (token confusion attack)
    if payload.get("type") != "access":
        raise credentials_exception

    # 3. Extract claims
    user_id: str | None = payload.get("sub")
    jti: str | None = payload.get("jti")
    if user_id is None or jti is None:
        raise credentials_exception

    # 4. Check blacklist (logout / rotation revocation)
    if await redis.get(RedisKeys.blacklist(jti)):
        raise credentials_exception

    # 5. Check per-user global revocation (triggered on suspected token theft)
    revoke_ts = await redis.get(f"revoke_all:{user_id}")
    if revoke_ts:
        token_iat = payload.get("iat", 0)
        if isinstance(token_iat, float):
            token_iat = int(token_iat)
        if token_iat <= int(revoke_ts):
            raise credentials_exception

    # 6. Load user from DB
    result = await db.execute(
        select(User).where(User.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception

    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """
    Extends get_current_user. Additionally checks is_active.
    Use this on any route that should reject disabled accounts.
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled.",
        )
    return current_user


async def get_current_superuser(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    """
    Only allows superusers. Use on admin-only routes.
    Returns 403 (not 401) — the user IS authenticated, just not authorised.
    """
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions.",
        )
    return current_user


# ---------------------------------------------------------------------------
# Typed shortcuts — import and use these in route signatures
# ---------------------------------------------------------------------------
CurrentUser = Annotated[User, Depends(get_current_active_user)]
SuperUser = Annotated[User, Depends(get_current_superuser)]