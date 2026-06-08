
from sqlalchemy.engine import default
from typing import Dict, Optional
import uuid
from datetime import datetime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Boolean, Text, Index
from app.models.base import Base, TimestampMixin

class JobPosting(Base, TimestampMixin):
    __tablename__ = "job_postings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )

    url: Mapped[str] = mapped_column(
        String(2048),
        nullable=False,
        unique=True,
        index=True
    )

    raw_text: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    parsed_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict
    )

    title: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    company: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    embedding_id: Mapped[str] = mapped_column(
        String(64),
        nullable=True,
        index=True
    )

    dedup_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=True,
        index=True
    )

    is_duplicate: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
    )

    # --- composite indexes for query patterns you will actually use ---
    __table_args__ = (
        Index("ix_job_postings_dedup_hash", "dedup_hash"),
        Index("ix_job_postings_status_created", "status", "created_at"),
        Index("ix_job_postings_company_title", "company", "title"),
    )

    def __repr__(self) -> str:
        return f"<JobPosting url={self.url!r} id={self.id!r}>"

