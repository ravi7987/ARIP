from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# ---------------------------------------------------------------------------
# Dependency: get_db
# ---------------------------------------------------------------------------
# This is the canonical FastAPI pattern for DB session injection.
#
# AsyncGenerator[AsyncSession, None] means:
#   - yields one AsyncSession
#   - sends nothing back (None)
#
# The try/finally guarantees the session is always closed, even if
# the route handler raises an exception mid-request.
#
# Usage in a router:
#   @router.get("/users")
#   async def list_users(db: AsyncSession = Depends(get_db)):

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
