import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_postings import JobPosting
from app.schemas.arip import IngestResponse, JobPostingSchema
from app.services.ingestion.extractor import ExtractionError, extract_structure
from app.services.ingestion.parser import (
    FetchContentError,
    FetchError,
    compute_url_hash,
    fetch_url,
    strip_boilerplate,
)

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def ingest(self, url: str) -> IngestResponse:
        """Run the full ingestion pipeline for a single job posting URL.

        Pipeline:
          1. Dedup check — return immediately if URL was already ingested.
          2. Fetch HTML from the URL.
          3. Strip boilerplate to get plain text.
          4. Extract structured fields with LlamaParse.
          5. Persist a JobPosting row and return IngestResponse.

        Raises:
            FetchError subclass: network / HTTP / content failure.
            ExtractionError: LlamaParse returned an unusable response.
        """
        dedup_hash = compute_url_hash(url)
        
        existing = await self._find_by_hash(dedup_hash)
        if existing is not None:
            logger.info("Duplicate URL detected — hash=%s url=%s", dedup_hash, url)
            return IngestResponse(
                id=existing.id,
                url=existing.url,
                status=existing.status,
                is_duplicate=True,
                title=existing.title,
                company=existing.company,
            )
        
        html = await fetch_url(url)
        
        raw_text = strip_boilerplate(html)
        print("Fetched HTML: %s", raw_text)
        parsed: JobPostingSchema = await extract_structure(raw_text)
        logger.debug("Parsed fields: title=%r company=%r data=%r", parsed.title, parsed.company, parsed)

        posting = JobPosting(
            url=url,
            raw_text=raw_text,
            parsed_json=parsed.model_dump(),
            title=parsed.title,
            company=parsed.company,
            dedup_hash=dedup_hash,
            is_duplicate=False,
            status="completed",
        )
        self.db.add(posting)
        await self.db.commit()
        await self.db.refresh(posting)

        logger.info(
            "Ingested job posting id=%s title=%r company=%r url=%s",
            posting.id, posting.title, posting.company, url,
        )

        return IngestResponse(
            id=posting.id,
            url=posting.url,
            status=posting.status,
            is_duplicate=False,
            title=posting.title,
            company=posting.company,
        )

    async def _find_by_hash(self, dedup_hash: str) -> JobPosting | None:
        result = await self.db.execute(
            select(JobPosting).where(JobPosting.dedup_hash == dedup_hash)
        )
        return result.scalar_one_or_none()
