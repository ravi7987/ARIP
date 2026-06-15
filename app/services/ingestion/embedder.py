import asyncio
import logging
import uuid
from functools import lru_cache
from typing import Final

from fastembed import TextEmbedding
from qdrant_client import AsyncQdrantClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COLLECTION_NAME: Final[str] = "job_postings"
VECTOR_SIZE: Final[int] = 384          # BAAI/bge-small-en-v1.5 output dim
_MODEL_NAME: Final[str] = "BAAI/bge-small-en-v1.5"


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _get_model() -> TextEmbedding:
    """Singleton TextEmbedding model — ONNX, loaded once per process."""
    logger.info("Loading fastembed model %s", _MODEL_NAME)
    return TextEmbedding(model_name=_MODEL_NAME)


async def embed_text(text: str) -> list[float]:
    """Return a 384-dimensional embedding for *text*.

    fastembed is CPU-bound and synchronous; run it in the default thread pool
    so it does not block the asyncio event loop.
    """
    loop = asyncio.get_running_loop()
    model = _get_model()
    result = await loop.run_in_executor(None, lambda: list(model.embed([text])))
    return result[0].tolist()


# ---------------------------------------------------------------------------
# Semantic duplicate check
# ---------------------------------------------------------------------------

async def is_semantic_duplicate(
    embedding: list[float],
    threshold: float,
    client: AsyncQdrantClient,
    collection: str = COLLECTION_NAME,
) -> uuid.UUID | None:
    """Return the matched posting's UUID if the nearest neighbour scores above
    *threshold*, otherwise None.

    Returning the matched id (rather than a bare bool) lets the caller fetch the
    existing JobPosting row and build a proper duplicate response without a
    second Qdrant query.

    Uses Qdrant's score_threshold so the network round-trip transfers at most
    one result when no duplicate exists, keeping latency minimal.

    Args:
        embedding:  Dense vector produced by embed_text().
        threshold:  Cosine similarity cutoff (0.0–1.0). Typical value: 0.92.
        client:     Shared AsyncQdrantClient instance.
        collection: Qdrant collection to search. Defaults to COLLECTION_NAME.

    Returns:
        UUID of the matching JobPosting, or None if no near-duplicate found.
    """
    try:
        response = await client.query_points(
            collection_name=collection,
            query=embedding,
            limit=1,
            score_threshold=threshold,
        )
        hits = response.points
        if hits:
            matched_id = uuid.UUID(str(hits[0].id))
            logger.info(
                "Semantic duplicate found — score=%.4f id=%s",
                hits[0].score,
                matched_id,
            )
            return matched_id
        return None
    except Exception as exc:
        # A missing collection or unreachable Qdrant must not crash ingestion.
        logger.warning("Qdrant semantic-dedup check failed: %s", exc)
        return None
