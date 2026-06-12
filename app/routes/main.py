from fastapi import APIRouter

from app.routes.arip import router as AripRouter
from app.routes.auth import router as AuthRouter

router = APIRouter(prefix="/api/v1")

router.include_router(AuthRouter)
router.include_router(AripRouter)

