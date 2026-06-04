from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from app.routes.main import router as main_router
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from app.core.config import get_settings
from app.db.sessions import engine
from app.db.redis import close_redis_pool, get_redis_pool

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # ── STARTUP ──────────────────────────────────────────────────
    # Initialise the Redis pool eagerly so the first request isn't
    # penalised with pool creation latency.
    get_redis_pool()

    async with engine.connect() as conn:
        await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
 
    yield  # ← application runs here
 
    # ── SHUTDOWN ─────────────────────────────────────────────────
    await engine.dispose() 
    await close_redis_pool()

 
def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        lifespan=lifespan,
        # Disable docs in production — they expose your API schema.
        docs_url="/docs",
        redoc_url=None,
    )
 
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Lock this down in prod!
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
 
    app.include_router(main_router)
 
    return app

app = create_app()

