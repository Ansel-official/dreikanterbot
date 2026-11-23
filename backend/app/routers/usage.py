"""配额与个人用量查询。"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query

from ..config import settings
from ..database import get_pool
from ..deps import CurrentUser, get_current_user
from ..models import UsageOut
from ..services.rate_limit import peek_daily_quota

router = APIRouter(prefix="/usage", tags=["配额"])


@router.get("/me", response_model=UsageOut, summary="我的今日额度")
async def my_usage(user: CurrentUser = Depends(get_current_user)) -> dict:
    quota = await peek_daily_quota(user.id, user.role)
    return quota.to_public()


@router.get("/me/history", summary="我的近 14 天用量")
async def my_usage_history(
    days: int = Query(default=14, ge=1, le=90),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        tz = ZoneInfo(settings.app_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = timezone.utc

    now_local = datetime.now(tz)
    today = now_local.date()
    start_date = today - timedelta(days=days - 1)
    start_utc = datetime.combine(start_date, time.min, tzinfo=tz).astimezone(timezone.utc)

    # 在 Python 中按应用时区归档，避免依赖 PostgreSQL 安装的时区数据库。
    rows = await get_pool().fetch(
        """
        SELECT created_at, kind, tokens_prompt, tokens_completion
        FROM usage_logs
        WHERE user_id = $1 AND created_at >= $2
        """,
        user.id,
        start_utc,
    )
    by_day: dict[str, dict] = {}
    for row in rows:
        day = row["created_at"].astimezone(tz).date().isoformat()
        item = by_day.setdefault(day, {"day": day, "requests": 0, "tokens": 0, "asr": 0})
        item["requests"] += 1
        item["tokens"] += int(row["tokens_prompt"] or 0) + int(row["tokens_completion"] or 0)
        if row["kind"] == "asr":
            item["asr"] += 1

    daily = []
    for offset in range(days):
        day = (start_date + timedelta(days=offset)).isoformat()
        daily.append(by_day.get(day, {"day": day, "requests": 0, "tokens": 0, "asr": 0}))
    return {"days": days, "items": daily}
