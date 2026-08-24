import time
from typing import Any

import orjson
from loguru import logger

from app.core.config import get_settings

_redis = None
_memory: dict[str, tuple[bytes, float | None]] = {}


def get_redis():
    """Redis client (None in local_mode — use memory cache)."""
    global _redis
    settings = get_settings()
    if settings.local_mode:
        return None
    if _redis is None:
        from redis.asyncio import Redis

        _redis = Redis.from_url(settings.redis_url, decode_responses=False)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
    _memory.clear()


class CacheKeys:
    SERVICES_ALL = "services:all"
    SERVICES_BY_CATEGORY = "services:category:{category_id}"
    SERVICES_BY_PLATFORM = "services:platform:{platform}"
    CATEGORIES = "categories:all"
    CATEGORIES_BY_PLATFORM = "categories:platform:{platform}"
    PLATFORMS = "platforms:all"
    PANEL_BALANCE = "panel:balance"


def _memory_get(key: str) -> bytes | None:
    item = _memory.get(key)
    if item is None:
        return None
    payload, expires_at = item
    if expires_at is not None and time.time() > expires_at:
        _memory.pop(key, None)
        return None
    return payload


def _memory_set(key: str, payload: bytes, ttl: int) -> None:
    expires_at = time.time() + ttl if ttl > 0 else None
    _memory[key] = (payload, expires_at)


async def cache_set(key: str, value: object, ttl: int | None = None) -> None:
    settings = get_settings()
    payload = orjson.dumps(value)
    expire = ttl or settings.cache_ttl_seconds
    redis = get_redis()
    if redis is None:
        _memory_set(key, payload, expire)
        return
    await redis.set(key, payload, ex=expire)


async def cache_get(key: str) -> Any | None:
    redis = get_redis()
    if redis is None:
        raw = _memory_get(key)
    else:
        raw = await redis.get(key)
    if raw is None:
        return None
    return orjson.loads(raw)


async def cache_delete(*keys: str) -> None:
    if not keys:
        return
    redis = get_redis()
    if redis is None:
        for key in keys:
            _memory.pop(key, None)
        return
    await redis.delete(*keys)


def log_cache_backend() -> None:
    settings = get_settings()
    if settings.local_mode:
        logger.info("Cache backend: in-memory (local_mode)")
    else:
        logger.info("Cache backend: Redis")
