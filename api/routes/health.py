from fastapi import APIRouter
from api.models.schemas import HealthResponse
from api.db.connection import get_pool
from api.core.cache import ping_redis

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check():
    # Check Postgres
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        postgres_status = "ok"
    except Exception as e:
        postgres_status = f"error: {str(e)}"

    # Check Redis
    redis_ok = await ping_redis()
    redis_status = "ok" if redis_ok else "error: unreachable"

    return HealthResponse(
        status="ok" if postgres_status == "ok" and redis_status == "ok" else "degraded",
        postgres=postgres_status,
        redis=redis_status,
    )