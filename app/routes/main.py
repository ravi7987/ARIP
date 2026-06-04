from fastapi import APIRouter
from app.routes.auth import router as AuthRouter

router = APIRouter(
    prefix = "/api/v1"
)

router.include_router(AuthRouter)

