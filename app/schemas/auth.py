# schemas/auth.py

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """POST /auth/login — accepts username OR email + password."""
    username: str = Field(..., description="Username or email address.")
    password: str = Field(..., description="Raw password.")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Access token TTL in seconds.")


class RefreshRequest(BaseModel):
    """POST /auth/refresh — swap a refresh token for new access token."""
    refresh_token: str


class MessageResponse(BaseModel):
    """Generic success message for endpoints that don't return data."""
    message: str