"""每日业务配额、IP 限速、JWT 黑名单、会话生成锁。

Redis 是第一选择；Redis 故障时自动降级为进程内计数（单 worker 部署下仍然有效），
降级期间重启会丢失计数，生产环境请保证 Redis 可用。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from redis.exceptions import RedisError

from ..config import settings
from ..redis_client import get_redis

logger = logging.getLogger(__name__)


def _tz() -> tzinfo:
    try:
        return ZoneInfo(settings.app_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def current_day_key() -> str:
    return datetime.now(_tz()).strftime("%Y-%m-%d")


def next_reset_at() -> datetime:
    now_local = datetime.now(_tz())
    tomorrow = (now_local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tomorrow.astimezone(timezone.utc)


def _seconds_until_reset() -> int:
    return max(60, int((next_reset_at() - datetime.now(timezone.utc)).total_seconds()))


@dataclass
class DailyQuota:
    role: str
    used: int
    limit: int | None
    remaining: int | None
    resets_at: datetime

    def to_public(self) -> dict:
        return {
            "role": self.role,
            "used": self.used,
            "limit": self.limit,
            "remaining": self.remaining,
            "resets_at": self.resets_at.isoformat().replace("+00:00", "Z"),
        }


class QuotaExceeded(Exception):
    def __init__(self, quota: DailyQuota):
        self.quota = quota
        super().__init__("今日额度已用完")


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int = 60):
        self.retry_after = retry_after
        super().__init__("请求过于频繁")


def role_limit(role: str) -> int | None:
    if role == "admin":
        return None
    if role == "guest":
        return settings.guest_daily_limit
    return settings.member_daily_limit


def _quota_for(role: str, used: int) -> DailyQuota:
    limit = role_limit(role)
    if limit is None:
        return DailyQuota(role=role, used=used, limit=None, remaining=None, resets_at=next_reset_at())
    return DailyQuota(
        role=role,
        used=used,
        limit=limit,
        remaining=max(0, limit - used),
        resets_at=next_reset_at(),
    )


# ---------------------------------------------------------------------------
# 进程内降级计数
# ---------------------------------------------------------------------------
_local_lock = asyncio.Lock()
_local_counts: dict[str, int] = {}
_local_expiry: dict[str, float] = {}
_local_blacklist: dict[str, float] = {}
_local_session_locks: dict[str, tuple[str, float]] = {}


def _cleanup_local(now: float) -> None:
    for store in (_local_expiry, _local_blacklist):
        for key, expire_at in list(store.items()):
            if expire_at <= now:
                store.pop(key, None)
    for key, (_, expire_at) in list(_local_session_locks.items()):
        if expire_at <= now:
            _local_session_locks.pop(key, None)


def _local_day_key(user_id: int) -> str:
    return f"{current_day_key()}:{user_id}"


async def consume_daily_quota(user_id: int, role: str) -> DailyQuota:
    """原子消费 1 次额度；超限抛出 QuotaExceeded。admin 不计数。"""
    limit = role_limit(role)
    if limit is None:
        return _quota_for(role, 0)

    key = f"quota:{current_day_key()}:{user_id}"
    ttl = _seconds_until_reset() + 86_400
    redis = get_redis()
    if redis is not None:
        try:
            pipe = redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, ttl)
            used, _ = await pipe.execute()
            used = int(used)
            quota = _quota_for(role, used)
            if used > limit:
                raise QuotaExceeded(quota)
            return quota
        except RedisError as exc:
            logger.warning("Redis 配额计数失败，降级为进程内计数：%s", exc)

    async with _local_lock:
        now = time.time()
        _cleanup_local(now)
        local_key = _local_day_key(user_id)
        used = _local_counts.get(local_key, 0) + 1
        _local_counts[local_key] = used
        _local_expiry[local_key] = now + 2 * 86_400
        quota = _quota_for(role, used)
        if used > limit:
            raise QuotaExceeded(quota)
        return quota


async def peek_daily_quota(user_id: int, role: str) -> DailyQuota:
    limit = role_limit(role)
    if limit is None:
        return _quota_for(role, 0)

    key = f"quota:{current_day_key()}:{user_id}"
    redis = get_redis()
    if redis is not None:
        try:
            raw = await redis.get(key)
            return _quota_for(role, int(raw or 0))
        except (RedisError, ValueError) as exc:
            logger.warning("读取 Redis 配额失败，使用进程内计数：%s", exc)

    async with _local_lock:
        _cleanup_local(time.time())
        return _quota_for(role, _local_counts.get(_local_day_key(user_id), 0))


# ---------------------------------------------------------------------------
# IP 限速（登录、ASR 等高风险接口）
# ---------------------------------------------------------------------------
async def enforce_ip_rate(bucket: str, identifier: str, limit: int, window_seconds: int) -> None:
    key = f"ratelimit:{bucket}:{identifier}"
    redis = get_redis()
    if redis is not None:
        try:
            pipe = redis.pipeline()
            pipe.incr(key)
            pipe.expire(key, window_seconds)
            count, _ = await pipe.execute()
            if int(count) > limit:
                raise RateLimitExceeded(retry_after=window_seconds)
            return
        except RedisError as exc:
            logger.warning("Redis IP 限速失败，降级为进程内计数：%s", exc)

    async with _local_lock:
        now = time.time()
        _cleanup_local(now)
        count = _local_counts.get(key, 0) + 1
        _local_counts[key] = count
        _local_expiry[key] = now + window_seconds
        if count > limit:
            raise RateLimitExceeded(retry_after=window_seconds)


# ---------------------------------------------------------------------------
# JWT 黑名单（登出即失效）
# ---------------------------------------------------------------------------
async def blacklist_token(jti: str, expires_at: datetime) -> None:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    ttl = max(60, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    redis = get_redis()
    if redis is not None:
        try:
            await redis.set(f"jwt:blacklist:{jti}", "1", ex=ttl)
            return
        except RedisError as exc:
            logger.warning("Redis 黑名单写入失败：%s", exc)
    async with _local_lock:
        _local_blacklist[jti] = time.time() + ttl


async def is_token_blacklisted(jti: str) -> bool:
    redis = get_redis()
    if redis is not None:
        try:
            return bool(await redis.exists(f"jwt:blacklist:{jti}"))
        except RedisError as exc:
            logger.warning("Redis 黑名单查询失败：%s", exc)
    async with _local_lock:
        _cleanup_local(time.time())
        return jti in _local_blacklist


# ---------------------------------------------------------------------------
# 会话生成锁：防止同一会话在多个标签页/设备同时生成
# ---------------------------------------------------------------------------
async def acquire_session_lock(session_id: int, owner: str, ttl: int = 600) -> bool:
    key = f"chat:lock:{session_id}"
    redis = get_redis()
    if redis is not None:
        try:
            return bool(await redis.set(key, owner, nx=True, ex=ttl))
        except RedisError as exc:
            logger.warning("Redis 会话锁失败：%s", exc)

    async with _local_lock:
        now = time.time()
        existing = _local_session_locks.get(key)
        if existing and existing[1] > now:
            return False
        _local_session_locks[key] = (owner, now + ttl)
        return True


async def release_session_lock(session_id: int, owner: str) -> None:
    key = f"chat:lock:{session_id}"
    redis = get_redis()
    if redis is not None:
        try:
            # 只删除自己持有的锁，避免误删其他连接的锁
            script = """
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            else
                return 0
            end
            """
            await redis.eval(script, 1, key, owner)
            return
        except RedisError as exc:
            logger.warning("Redis 会话锁释放失败：%s", exc)

    async with _local_lock:
        existing = _local_session_locks.get(key)
        if existing and existing[0] == owner:
            _local_session_locks.pop(key, None)
