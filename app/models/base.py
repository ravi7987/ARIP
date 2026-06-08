# models/base.py
# Every table in your system will need created_at / updated_at.
# Define it ONCE here as a mixin and inherit it everywhere.
# This is the DRY (Don't Repeat Yourself) principle applied to ORM models.

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

class JobPostingStatus:
    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"

class AnalysisStatus:
    PENDING = "pending"
    COMPLETED = "completed"
    DEGRADED = "degraded"    # circuit breaker fired
    FAILED = "failed"  

class Base(DeclarativeBase):
    pass


class TimestampMixin:

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),          
        nullable=False,
    )