# models/user.py

import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.analysis_result import AnalysisResult


class User(Base, TimestampMixin):

    __tablename__ = "users"

    # Primary key
    # LESSON: uuid.uuid4 is the *default factory*, called per row.
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,  
        nullable=False,
    )

    username: Mapped[str] = mapped_column(
        String(50),
        nullable=False,  
        unique=True,
        index=True       
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,            
    )

    hashed_password: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Refresh token: storing just the *hash* of the token, not the
    # raw value. If the DB is breached, hashes are useless without
    # the original token. Null = no active session.
    refresh_token_hash: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )

    # Status flags
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        comment="True once email verification is complete.",
    )

    analysis_results: Mapped[list["AnalysisResult"]] = relationship(
        "AnalysisResult",
        back_populates="user",
        lazy="select",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r} email={self.email!r}>"