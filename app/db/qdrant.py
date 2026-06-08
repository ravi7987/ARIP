from collections.abc import AsyncGenerator

from qdrant_client import AsyncQdrantClient

from app.core.config import get_settings

settings = get_settings()

# ---------------------------------------------------------------------------
# Singleton (module-level)
# ---------------------------------------------------------------------------
# One AsyncQdrantClient for the entire application lifetime.
# Creating a client per-request would open a new HTTP connection on every
# call — expensive and unnecessary given that AsyncQdrantClient is
# thread-safe and designed to be shared.
_qdrant_client: AsyncQdrantClient | None = None


def get_qdrant_client_instance() -> AsyncQdrantClient:
    """Return the shared client, creating it on first call.

    Called once during app lifespan startup (see main.py) so the first
    real request is never penalised with connection setup latency.
    """
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = AsyncQdrantClient(
            url=settings.QDRANT_URL,
            # api_key=None disables auth — correct for local deployments.
            api_key=settings.QDRANT_API_KEY or None,
        )
    return _qdrant_client


async def close_qdrant_client() -> None:
    """Close the client and release its underlying HTTP session.

    Called in main.py lifespan teardown. Without this you get
    'Unclosed client session' warnings from aiohttp on shutdown.
    """
    global _qdrant_client
    if _qdrant_client is not None:
        await _qdrant_client.close()
        _qdrant_client = None


# ---------------------------------------------------------------------------
# Dependency: get_qdrant_client
# ---------------------------------------------------------------------------
# Yields the shared AsyncQdrantClient for FastAPI Depends injection.
# No per-request setup/teardown is needed — the client is stateless between
# calls, so we just yield the singleton and return.
#
# Usage in a router or service:
#   @router.get("/search")
#   async def search(
#       q: str,
#       qdrant: AsyncQdrantClient = Depends(get_qdrant_client),
#   ):
#       hits = await qdrant.search(collection_name="jobs", query_vector=...)
async def get_qdrant_client() -> AsyncGenerator[AsyncQdrantClient, None]:
    yield get_qdrant_client_instance()
