import uuid

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Ingestion pipeline
# ---------------------------------------------------------------------------

class IngestRequest(BaseModel):
    """POST /ingest — submit a job posting URL for ingestion."""

    url: str = Field(..., description="Fully-qualified URL of the job posting.")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        if len(v) > 2048:
            raise ValueError("URL exceeds maximum length of 2048 characters.")
        return v


class IngestResponse(BaseModel):
    """Returned after a job posting is ingested (or found as a duplicate)."""

    id: uuid.UUID = Field(..., description="Database ID of the JobPosting record.")
    url: str = Field(..., description="Canonical URL after redirect resolution.")
    status: str = Field(
        ...,
        description="Pipeline status: pending | completed | degraded | failed.",
    )
    is_duplicate: bool = Field(
        ...,
        description="True if this URL was already present in the system.",
    )
    title: str | None = Field(None, description="Extracted job title.")
    company: str | None = Field(None, description="Extracted company name.")


# ---------------------------------------------------------------------------
# Structured extraction
# ---------------------------------------------------------------------------

class JobPostingSchema(BaseModel):
    """Structured representation of a job posting extracted by LlamaParse.
    """

    title: str | None = None
    company: str | None = None
    location: str | None = None
    seniority: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    salary_range: str | None = None
    raw_text: str
