import uuid
from typing import TYPE_CHECKING, Optional
from sqlalchemy import String, Text, Float, Integer, Boolean, Index, text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class AnalysisResult(Base, TimestampMixin):
    __tablename__ = "analysis_results"

    # --- identity ---
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
        nullable=False,
    )

    # --- ownership ---
    # every analysis belongs to an authenticated user
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --- input snapshot ---
    # store a hash of the CV text, not the full text
    # full CV text can be large and changes rarely — store it separately if needed
    cv_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    # the query generated from the CV that was sent to the retriever
    retrieval_query: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    # which job postings were retrieved and used as context
    # list of JobPosting UUIDs — stored as JSONB array for queryability
    retrieved_posting_ids: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )

    # --- agent output ---
    analysis_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    # full structured output from the analysis node
    # contains skill gaps, matched skills, recommendations
    analysis_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )

    # --- circuit breaker state ---
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    max_retries: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
    )
    # list of claim strings that failed the critique node
    # e.g. ["Role requires Kubernetes", "5 years React required"]
    failed_claims: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )
    # list of query strings attempted — for oscillation detection audit trail
    query_history: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
    )

    # --- eval metrics ---
    # RAGAS faithfulness score: were claims grounded in source JDs?
    faithfulness_score: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,    # nullable: eval may not run on every request in dev
    )
    # RAGAS context_recall: did retrieval surface the right postings?
    context_recall_score: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )
    # single hallucination rate for this specific run (0.0 - 1.0)
    hallucination_rate: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
    )

    # --- pipeline status ---
    # mirrors the status pattern from JobPosting — consistent vocabulary
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",   # pending | completed | degraded | failed
    )
    # True if circuit breaker fired — redundant with status="degraded"
    # but explicit boolean is faster to query than string comparison
    is_degraded: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    # overall confidence score, updated on each retry iteration
    confidence_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
    )

    # --- relationships ---
    user: Mapped["User"] = relationship(
        "User",
        back_populates="analysis_results",
        lazy="select",
    )

    # --- composite indexes ---
    __table_args__ = (
        # most common query: all results for a user, newest first
        Index("ix_analysis_results_user_created", "user_id", "created_at"),
        # filter degraded results for monitoring dashboards
        Index("ix_analysis_results_status", "status"),
        # filter by confidence for reporting: "show me low-confidence analyses"
        Index("ix_analysis_results_confidence", "confidence_score"),
    )

    def __repr__(self) -> str:
        return (
            f"<AnalysisResult id={self.id!r} "
            f"status={self.status!r} "
            f"confidence={self.confidence_score:.2f} "
            f"retries={self.retry_count}/{self.max_retries}>"
        )