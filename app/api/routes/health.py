from fastapi import APIRouter
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.redis import get_redis
from app.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    # DB check
    db_status = "ok"
    try:
        async with AsyncSessionLocal() as s:
            await s.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    # Redis check
    redis_status = "ok"
    try:
        r = await get_redis()
        await r.ping()
    except Exception:
        redis_status = "error"

    return HealthResponse(
        status="ok" if db_status == "ok" and redis_status == "ok" else "degraded",
        version="0.1.0",
        db=db_status,
        redis=redis_status,
    )