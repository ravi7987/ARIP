import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from app.core.config import get_settings

settings = get_settings()

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
# CryptContext manages multiple hashing schemes and handles upgrades.
# deprecated="auto" means: if a user was hashed with an older scheme,
# passlib flags it for rehashing on next login — without breaking them.

pwd_context = PasswordHash((Argon2Hasher(),))


def hash_password(plain_password: str) -> str:
    """Hash a plain-text password. Call once at registration."""
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a plain-text password against its stored hash.
    """
    return pwd_context.verify(plain_password, hashed_password)


def verify_and_update(plain_password: str, hashed_password: str) -> tuple[bool, str | None]:
    """
    Verifies the password and returns a new hash if the algorithm
    needs upgrading. Returns (is_valid, new_hash_or_none).
    new_hash_or_none is None if no rehash was needed.
    """
    return pwd_context.verify_and_update(plain_password, hashed_password)


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
# What is jti (JWT ID)?
# A UUID embedded in every token. Without it, you cannot revoke a single
# token — you'd have to invalidate ALL tokens for that user.
# With jti: on logout, store jti in Redis (TTL = remaining token life).
# On every request, check Redis. If jti is there → token is blacklisted.
# Stateless JWT + stateful revocation. 

def _build_token(
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    extra_claims: dict | None = None,
) -> tuple[str, str]:
    """Internal factory. Returns (encoded_jwt, jti)."""
    jti = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    payload = {
        "sub": subject,       # User UUID as string.
        "type": token_type,   # "access" or "refresh" — prevents token confusion attacks.
        "jti": jti,           # Unique token ID for blacklisting.
        "iat": now,
        "exp": now + expires_delta,
        **(extra_claims or {}),
    }

    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, jti


def create_access_token(subject: str) -> tuple[str, str]:
    """Short-lived access token. Returns (token, jti)."""
    expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return _build_token(subject, token_type="access", expires_delta=expires)


def create_refresh_token(subject: str) -> tuple[str, str]:
    """Long-lived refresh token. Returns (token, jti)."""
    expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return _build_token(subject, token_type="refresh", expires_delta=expires)


def decode_token(token: str) -> dict:
    """
    Decode and verify a JWT. Raises jose.JWTError on any failure.
    """
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
    )