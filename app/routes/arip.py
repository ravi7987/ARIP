from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Response, status

from qdrant_client import AsyncQdrantClient

from app.db.qdrant import get_qdrant_client
from app.dependencies.auth import CurrentUser, DbSession
from app.schemas.arip import IngestRequest, IngestResponse
from app.services.ingestion.extractor import ExtractionError
from app.services.ingestion.parser import (
    FetchBlockedError,
    FetchContentError,
    FetchHTTPError,
    FetchNetworkError,
    FetchTimeoutError,
)
from app.services.ingestion.service import IngestionService

router = APIRouter(prefix="/arip", tags=["ARIP"])


# ---------------------------------------------------------------------------
# Service factory
# ---------------------------------------------------------------------------

def get_ingestion_service(
    db: DbSession,
    qdrant: Annotated[AsyncQdrantClient, Depends(get_qdrant_client)],
) -> IngestionService:
    return IngestionService(db=db, qdrant=qdrant)


IngestionServiceDep = Annotated[IngestionService, Depends(get_ingestion_service)]


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------
# Maps typed ingestion exceptions → HTTP status codes + user-facing details.
# One place to change status codes; the service layer stays HTTP-free.

def _raise_http_for(exc: Exception, url: str) -> NoReturn:
    if isinstance(exc, FetchTimeoutError):
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"The job posting server did not respond in time: {url}",
        )
    if isinstance(exc, FetchHTTPError):
        if 400 <= exc.status_code < 500:
            # 4xx → the URL itself is the problem (404, 403, etc.)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"URL returned HTTP {exc.status_code} — verify the link is publicly accessible.",
            )
        # 5xx / 429 → upstream server problem
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"The job posting server returned HTTP {exc.status_code}.",
        )
    if isinstance(exc, FetchNetworkError):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not reach the job posting URL — check the address and try again.",
        )
    if isinstance(exc, FetchBlockedError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    if isinstance(exc, (FetchContentError, ExtractionError)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The URL does not appear to contain a parseable job posting.",
        )
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a job posting URL",
    description=(
        "Fetches the page, strips boilerplate, extracts structured fields "
        "with LlamaParse, and persists the result. "
        "Returns **201** when a new record is created, **200** when the URL "
        "was already present (duplicate)."
    ),
)
async def ingest_job_posting(
    payload: IngestRequest,
    svc: IngestionServiceDep,
    response: Response,
    _: CurrentUser,
) -> IngestResponse:
    try:
        result = await svc.ingest(str(payload.url))
    except (
        FetchTimeoutError,
        FetchHTTPError,
        FetchNetworkError,
        FetchBlockedError,
        FetchContentError,
        ExtractionError,
    ) as exc:
        _raise_http_for(exc, str(payload.url))

    if result.is_duplicate:
        response.status_code = status.HTTP_200_OK

    return result
