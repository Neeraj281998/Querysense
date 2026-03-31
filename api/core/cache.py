import json
import hashlib
import redis.asyncio as aioredis
from typing import Optional
from api.core.config import get_settings

settings = get_settings()

_redis_client = None


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def close_redis():
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None


def make_cache_key(query: str, database_url: str) -> str:
    """
    Creates a unique cache key from the normalized query + database URL.
    Same query on different databases gets different cache entries.
    """
    # Normalize: lowercase, strip whitespace, collapse spaces
    normalized = " ".join(query.lower().split())
    raw = f"{normalized}::{database_url}"
    return "querysense:" + hashlib.sha256(raw.encode()).hexdigest()


async def get_cached(key: str) -> Optional[dict]:
    """
    Returns cached result if it exists, None otherwise.
    """
    try:
        redis = await get_redis()
        value = await redis.get(key)
        if value:
            return json.loads(value)
        return None
    except Exception:
        # Cache failure should never break the main flow
        return None


async def set_cached(key: str, value: dict, ttl: int = 86400):
    """
    Stores result in cache with TTL (default 24 hours).
    """
    try:
        redis = await get_redis()
        await redis.setex(key, ttl, json.dumps(value, default=str))
    except Exception:
        # Cache failure should never break the main flow
        pass


async def invalidate(key: str):
    """
    Deletes a specific cache entry.
    """
    try:
        redis = await get_redis()
        await redis.delete(key)
    except Exception:
        pass


async def ping_redis() -> bool:
    """
    Health check — returns True if Redis is reachable.
    """
    try:
        redis = await get_redis()
        return await redis.ping()
    except Exception:
        return False