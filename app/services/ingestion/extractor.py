import json
import logging
from typing import Any, Final

from llama_parse import LlamaParse, ResultType

from app.core.config import get_settings
from app.schemas.arip import JobPostingSchema

logger = logging.getLogger(__name__)

settings = get_settings()

# ---------------------------------------------------------------------------
# Extraction schema
# ---------------------------------------------------------------------------
# raw_text is intentionally absent — it is the caller's input, not something
# LlamaParse should extract from the document.
_EXTRACTION_SCHEMA: Final[dict] = {
    "type": "object",
    "properties": {
        "title": {
            "type": ["string", "null"],
            "description": "Exact job title as written in the posting.",
        },
        "company": {
            "type": ["string", "null"],
            "description": "Hiring company name.",
        },
        "location": {
            "type": ["string", "null"],
            "description": "Job location: city, country, 'Remote', 'Hybrid', etc.",
        },
        "seniority": {
            "type": ["string", "null"],
            "description": (
                "Seniority level inferred from the title or body: "
                "junior, mid, senior, staff, lead, principal, or null if unclear."
            ),
        },
        "required_skills": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Hard requirements: technologies, languages, frameworks, "
                "tools, or qualifications that the posting lists as mandatory."
            ),
        },
        "nice_to_have": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Preferred but optional skills: anything described as "
                "'nice to have', 'preferred', 'bonus', or 'plus'."
            ),
        },
        "salary_range": {
            "type": ["string", "null"],
            "description": (
                "Salary range exactly as written, e.g. '$120k–$160k', "
                "'€80,000–€100,000', or null if not mentioned."
            ),
        },
    },
    "required": ["required_skills", "nice_to_have"],
}

_PARSING_INSTRUCTION: Final[str] = (
    "This document is a job posting. "
    "Extract the structured fields defined in the schema. "
    "For required_skills, include every technology, language, framework, tool, "
    "or certification the posting treats as mandatory. "
    "For nice_to_have, include only skills explicitly described as optional, "
    "preferred, or a bonus. "
    "Return null for any field that is not mentioned in the document."
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def extract_structure(raw_text: str) -> JobPostingSchema:
    """Extract structured fields from a job posting's plain text body.

    Uses LlamaParse's structured-output mode: the text is sent to the
    LlamaParse API together with a JSON schema, and the response is a dict
    matching that schema. The result is validated into a JobPostingSchema.

    Args:
        raw_text: Plain text of a job posting, as returned by strip_boilerplate().

    Returns:
        A fully populated JobPostingSchema. Fields LlamaParse could not find
        are None / empty list. raw_text is always the original input.

    Raises:
        ExtractionError: LlamaParse returned an unusable response after the
            API call succeeded (malformed JSON, empty result, etc.).
        Any exception raised by the LlamaParse client is propagated as-is
        so the caller can decide on retry / fallback strategy.
    """
    parser = LlamaParse(
        api_key=settings.LLAMA_CLOUD_API_KEY,
        result_type=ResultType.JSON,
        structured_output=True,
        structured_output_json_schema=json.dumps(_EXTRACTION_SCHEMA),
        structured_output_json_schema_name="JobPostingSchema",
        parsing_instruction=_PARSING_INSTRUCTION,
        language="en",
        show_progress=False,
        verbose=False,
    )

    # LlamaParse accepts raw bytes directly — no temp file needed.
    # Passing bytes with a .txt hint avoids the overhead of disk I/O and
    # prevents leaving orphan files if the process is killed mid-run.
    encoded = raw_text.encode("utf-8")

    logger.debug(
        "Sending %d chars to LlamaParse for structured extraction", len(raw_text)
    )

    json_results: list[dict] = await parser.aget_json(encoded)

    if not json_results:
        raise ExtractionError("LlamaParse returned an empty result list.")

    extracted = _pick_structured_fields(json_results[0])

    logger.info(
        "Extracted fields — title=%r company=%r skills=%d nice_to_have=%d",
        extracted.get("title"),
        extracted.get("company"),
        len(extracted.get("required_skills") or []),
        len(extracted.get("nice_to_have") or []),
    )

    return JobPostingSchema(raw_text=raw_text, **extracted)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pick_structured_fields(result: dict[str, Any]) -> dict[str, Any]:
    """Pull the schema fields out of a LlamaParse JSON result dict.

    LlamaParse may nest the structured output under different keys depending
    on the API version. This function tries the most common locations in order
    and falls back to reading the root dict directly.
    """
    # LlamaParse ≥0.6 places structured data under "structured_output" when
    # structured_output=True is set.
    for key in ("structured_output", "structured_data", "result"):
        candidate = result.get(key)
        if isinstance(candidate, dict) and candidate:
            return _filter_schema_keys(candidate)

    # Flat result — structured fields are at the top level.
    return _filter_schema_keys(result)


_SCHEMA_KEYS: Final[frozenset[str]] = frozenset(_EXTRACTION_SCHEMA["properties"])


def _filter_schema_keys(data: dict[str, Any]) -> dict[str, Any]:
    """Keep only the keys that belong to the extraction schema."""
    out: dict[str, Any] = {}
    for key in _SCHEMA_KEYS:
        value = data.get(key)
        # Normalise empty lists so Field(default_factory=list) stays consistent.
        if key in ("required_skills", "nice_to_have"):
            out[key] = value if isinstance(value, list) else []
        else:
            out[key] = value if value != "" else None
    return out


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ExtractionError(Exception):
    """LlamaParse returned a response that could not be parsed into a
    JobPostingSchema. Distinct from LlamaParse's own client errors so callers
    can handle API failures and extraction failures separately."""
