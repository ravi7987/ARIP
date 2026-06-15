import logging
import uuid
from typing import Final

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import PointStruct
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_postings import JobPosting
from app.schemas.arip import IngestResponse, JobPostingSchema
from app.services.ingestion.embedder import (
    COLLECTION_NAME,
    embed_text,
    is_semantic_duplicate,
)
from app.services.ingestion.extractor import extract_structure
from app.services.ingestion.parser import (
    compute_dedup_hash,
    fetch_url,
    strip_boilerplate,
)

logger = logging.getLogger(__name__)

_SEMANTIC_THRESHOLD: Final[float] = 0.92


class IngestionService:
    def __init__(self, db: AsyncSession, qdrant: AsyncQdrantClient) -> None:
        self.db = db
        self.qdrant = qdrant

    async def ingest(self, url: str) -> IngestResponse:
        """Run the full ingestion pipeline for a single job posting URL.

        Pipeline (performance-ordered — cheapest checks first):
          1. URL dedup     — DB lookup; skip fetch entirely if already ingested.
          2. Fetch + strip — HTTP request + boilerplate removal.
          3. Hash dedup    — SHA-256 content match; skip embedding + LlamaParse.
          4. Semantic dedup — Qdrant nearest-neighbour; skip LlamaParse for near-dups.
          5. Extract       — LlamaParse structured extraction (most expensive step).
          6. Persist       — write JobPosting row; upsert vector into Qdrant.
        """
        # ── 1. URL dedup ─────────────────────────────────────────────────────
        existing = await self._find_by_url(url)
        if existing is not None:
            logger.info("Duplicate URL — url=%s", url)
            return self._duplicate_response(existing)

        # ── 2. Fetch + strip ─────────────────────────────────────────────────
        html = await fetch_url(url)
        raw_text = strip_boilerplate(html)

        # ── 3. Exact hash dedup ───────────────────────────────────────────────
        content_hash = compute_dedup_hash(raw_text)
        existing = await self._find_by_hash(content_hash)
        if existing is not None:
            logger.info("Duplicate content hash — hash=%s url=%s", content_hash, url)
            return self._duplicate_response(existing)

        # ── 4. Semantic dedup (only reached when hash check finds nothing) ────
        embedding = await embed_text(raw_text)
        matched_id = await is_semantic_duplicate(embedding, _SEMANTIC_THRESHOLD, self.qdrant)
        if matched_id is not None:
            logger.info("Semantic duplicate — matched_id=%s url=%s", matched_id, url)
            existing = await self._find_by_id(matched_id)
            if existing is not None:
                return self._duplicate_response(existing)

        # ── 5. Extract ────────────────────────────────────────────────────────
        parsed: JobPostingSchema = await extract_structure(raw_text)
        logger.debug("Parsed fields: title=%r company=%r", parsed.title, parsed.company)

        # ── 6. Persist ────────────────────────────────────────────────────────
        posting = JobPosting(
            url=url,
            raw_text=raw_text,
            parsed_json=parsed.model_dump(),
            title=parsed.title,
            company=parsed.company,
            dedup_hash=content_hash,
            is_duplicate=False,
            status="completed",
        )
        self.db.add(posting)
        await self.db.commit()
        await self.db.refresh(posting)

        await self.qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                PointStruct(
                    id=str(posting.id),
                    vector=embedding,
                    payload={"url": url, "title": parsed.title, "company": parsed.company},
                )
            ],
        )

        logger.info(
            "Ingested id=%s title=%r company=%r url=%s",
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

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _duplicate_response(self, existing: JobPosting) -> IngestResponse:
        return IngestResponse(
            id=existing.id,
            url=existing.url,
            status=existing.status,
            is_duplicate=True,
            title=existing.title,
            company=existing.company,
        )

    async def _find_by_id(self, posting_id: uuid.UUID) -> JobPosting | None:
        result = await self.db.execute(
            select(JobPosting).where(JobPosting.id == posting_id)
        )
        return result.scalar_one_or_none()

    async def _find_by_url(self, url: str) -> JobPosting | None:
        result = await self.db.execute(
            select(JobPosting).where(JobPosting.url == url)
        )
        return result.scalar_one_or_none()

    async def _find_by_hash(self, dedup_hash: str) -> JobPosting | None:
        result = await self.db.execute(
            select(JobPosting).where(JobPosting.dedup_hash == dedup_hash)
        )
        return result.scalar_one_or_none()
