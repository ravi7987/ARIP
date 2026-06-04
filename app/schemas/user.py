# schemas/user.py

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserBase(BaseModel):

    username: str = Field(
        ...,
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_-]+$",  # No spaces, no special chars.
        description="Unique username. Alphanumeric, underscores, hyphens only.",
        examples=["john_doe"],
    )
    email: EmailStr = Field(
        ...,
        description="Unique email address.",
        examples=["john@example.com"],
    )


class UserCreate(UserBase):

    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Raw password. Hashed before storage, never persisted.",
        examples=["Str0ng!Pass"],
    )

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if v.isalpha():
            raise ValueError("Password must contain at least one digit or special character.")
        if v.isdigit():
            raise ValueError("Password must contain at least one letter.")
        return v


class UserUpdate(BaseModel):

    username: str | None = Field(
        None,
        min_length=3,
        max_length=50,
        pattern=r"^[a-zA-Z0-9_-]+$",
    )
    email: EmailStr | None = None
    password: str | None = Field(None, min_length=8, max_length=128)


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_active: bool
    is_verified: bool
    is_superuser: bool
    created_at: datetime
    updated_at: datetime


class UserSummary(BaseModel):

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: EmailStr