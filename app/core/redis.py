"""
Redis client factory and ARQ queue helpers for async task ingestion.
"""
import json
from typing import Any

import redis.asyncio as aioredis
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Async Redis client (cache / pub-sub) ─────────────────────────────────────

_redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None


# ── ARQ worker pool (task queue) ──────────────────────────────────────────────

def _parse_redis_settings(url: str) -> RedisSettings:
    import urllib.parse

    parsed = urllib.parse.urlparse(url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int((parsed.path or "/0").lstrip("/")),
        password=parsed.password,
    )


_arq_pool: ArqRedis | None = None


async def get_queue() -> ArqRedis:
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(
            _parse_redis_settings(settings.redis_queue_url)
        )
    return _arq_pool


async def close_queue() -> None:
    global _arq_pool
    if _arq_pool:
        await _arq_pool.aclose()
        _arq_pool = None


# ── Pub/Sub helpers ───────────────────────────────────────────────────────────

CHANNEL_GRAPH_UPDATES = "opsgraph:graph_updates"
CHANNEL_INGESTION_STATUS = "opsgraph:ingestion_status"


async def publish_event(channel: str, payload: dict[str, Any]) -> None:
    r = await get_redis()
    await r.publish(channel, json.dumps(payload))
    logger.debug("redis.published", channel=channel)


async def cache_set(key: str, value: Any, ttl_seconds: int = 300) -> None:
    r = await get_redis()
    await r.setex(key, ttl_seconds, json.dumps(value))


async def cache_get(key: str) -> Any | None:
    r = await get_redis()
    raw = await r.get(key)
    return json.loads(raw) if raw else None


async def cache_delete(key: str) -> None:
    r = await get_redis()
    await r.delete(key)