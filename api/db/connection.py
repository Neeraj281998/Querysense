import asyncpg
from api.core.config import get_settings

settings = get_settings()

_pool = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=2,
            max_size=10,
            command_timeout=60,
        )
    return _pool


async def close_pool():
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def get_connection():
    pool = await get_pool()
    async with pool.acquire() as connection:
        yield connection