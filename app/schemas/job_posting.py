from pydantic import BaseModel, Field


class JobPostingSchema(BaseModel):
    title: str | None = None
    company: str | None = None
    location: str | None = None
    seniority: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)
    salary_range: str | None = None
    raw_text: str
