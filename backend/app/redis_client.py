"""Redis 客户端（限流计数、JWT 黑名单、会话生成锁）。

Redis 不可用时应用仍可启动：限流降级为进程内计数、黑名单降级为进程内集合，
但健康检查会返回 degraded，生产环境建议保持 Redis 可用。
"""
from __future__ import annotations

import logging

import redis.asyncio as aioredis

from .config import settings

logger = logging.getLogger(__name__)
_client: aioredis.Redis | None = None


async def init_redis() -> None:
    global _client
    if _client is not None:
        return
    try:
        client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=5,
            health_check_interval=30,
        )
        await client.ping()
        _client = client
        logger.info("Redis 已连接")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis 连接失败，限流降级为进程内计数：%s", exc)
        _client = None


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_redis() -> aioredis.Redis | None:
    return _client


async def redis_healthy() -> bool:
    if _client is None:
        return False
    try:
        return bool(await _client.ping())
    except Exception:  # noqa: BLE001
        return False
