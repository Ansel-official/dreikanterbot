"""管理员：用户管理、全局统计、API Key 审计。"""
from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import settings
from ..database import get_pool
from ..deps import CurrentUser, get_admin_user
from ..models import (
    AdminStats,
    MessageResponse,
    PasswordReset,
    RegisterRequest,
    UserPage,
    UserUpdateAdmin,
)
from ..security import PasswordPolicyError, hash_password
from ..serializers import api_key_public, user_public

router = APIRouter(prefix="/admin", tags=["管理员"])


def _tz():
    try:
        return ZoneInfo(settings.app_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


@router.get("/users", response_model=UserPage, summary="用户列表（搜索 / 筛选 / 分页）")
async def list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = Query(default=None, max_length=64),
    role: str | None = Query(default=None, pattern="^(admin|member|guest)$"),
    is_active: bool | None = Query(default=None),
    _: CurrentUser = Depends(get_admin_user),
) -> dict:
    where = ["1 = 1"]
    params: list = []
    if q:
        params.append(f"%{q.strip().lower()}%")
        where.append(f"username ILIKE ${len(params)}")
    if role:
        params.append(role)
        where.append(f"role = ${len(params)}")
    if is_active is not None:
        params.append(is_active)
        where.append(f"is_active = ${len(params)}")

    pool = get_pool()
    where_sql = " AND ".join(where)
    total = int(await pool.fetchval(f"SELECT COUNT(*) FROM users WHERE {where_sql}", *params) or 0)
    offset = (page - 1) * page_size
    rows = await pool.fetch(
        f"""
        SELECT * FROM users
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """,
        *params,
        page_size,
        offset,
    )
    return {
        "items": [user_public(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/users", status_code=201, summary="创建账号（仅管理员）")
async def create_user(
    payload: RegisterRequest,
    _: CurrentUser = Depends(get_admin_user),
) -> dict:
    try:
        password_hash = await asyncio.to_thread(hash_password, payload.password)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        row = await get_pool().fetchrow(
            """
            INSERT INTO users (username, password_hash, role)
            VALUES ($1, $2, $3)
            RETURNING *
            """,
            payload.username,
            password_hash,
            payload.role,
        )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(status_code=409, detail="用户名已存在") from exc
    return user_public(row)


@router.patch("/users/{user_id}", summary="修改角色或启用/禁用账号")
async def update_user(
    user_id: int,
    payload: UserUpdateAdmin,
    admin: CurrentUser = Depends(get_admin_user),
) -> dict:
    if payload.role is None and payload.is_active is None:
        raise HTTPException(status_code=400, detail="至少提供一个要修改的字段")

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(20240102)")
            target = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
            if target is None:
                raise HTTPException(status_code=404, detail="用户不存在")

            new_role = payload.role if payload.role is not None else target["role"]
            new_active = payload.is_active if payload.is_active is not None else target["is_active"]

            if user_id == admin.id:
                if new_role != "admin" or new_active is False:
                    raise HTTPException(status_code=400, detail="不能降级或禁用当前登录的管理员自己")
            if target["role"] == "admin" and (new_role != "admin" or not new_active):
                active_admins = int(
                    await conn.fetchval(
                        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = TRUE"
                    )
                    or 0
                )
                if active_admins <= 1:
                    raise HTTPException(status_code=400, detail="系统必须保留至少一个启用的管理员")

            row = await conn.fetchrow(
                """
                UPDATE users
                SET role = $1,
                    is_active = $2,
                    token_version = token_version + CASE WHEN $2 = FALSE THEN 1 ELSE 0 END,
                    updated_at = NOW()
                WHERE id = $3
                RETURNING *
                """,
                new_role,
                new_active,
                user_id,
            )
    return user_public(row)


@router.delete("/users/{user_id}", response_model=MessageResponse, summary="禁用账号（软删除）")
async def deactivate_user(
    user_id: int,
    admin: CurrentUser = Depends(get_admin_user),
) -> dict:
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能禁用当前登录的管理员自己")

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(20240102)")
            target = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
            if target is None:
                raise HTTPException(status_code=404, detail="用户不存在")
            if target["role"] == "admin":
                active_admins = int(
                    await conn.fetchval(
                        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = TRUE"
                    )
                    or 0
                )
                if active_admins <= 1:
                    raise HTTPException(status_code=400, detail="系统必须保留至少一个启用的管理员")
            await conn.execute(
                """
                UPDATE users
                SET is_active = FALSE, token_version = token_version + 1, updated_at = NOW()
                WHERE id = $1
                """,
                user_id,
            )
    return {"message": "账号已禁用，历史数据保留；重新启用后需要重新登录"}


@router.post("/users/{user_id}/reset-password", response_model=MessageResponse, summary="重置用户密码")
async def reset_password(
    user_id: int,
    payload: PasswordReset,
    admin: CurrentUser = Depends(get_admin_user),
) -> dict:
    if user_id == admin.id:
        raise HTTPException(
            status_code=400,
            detail="请使用「设置 → 账号 → 修改密码」修改自己的密码，避免当前会话被强制下线",
        )
    pool = get_pool()
    target = await pool.fetchrow("SELECT id, username FROM users WHERE id = $1", user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    try:
        password_hash = await asyncio.to_thread(hash_password, payload.new_password)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await pool.execute(
        """
        UPDATE users
        SET password_hash = $1, token_version = token_version + 1, updated_at = NOW()
        WHERE id = $2
        """,
        password_hash,
        user_id,
    )
    return {
        "message": f"已重置 {target['username']} 的密码，该用户所有已登录设备都会立即失效。"
    }


@router.get("/stats", response_model=AdminStats, summary="系统统计")
async def stats(_: CurrentUser = Depends(get_admin_user)) -> dict:
    pool = get_pool()
    users_total = int(await pool.fetchval("SELECT COUNT(*) FROM users") or 0)
    role_rows = await pool.fetch("SELECT role, COUNT(*)::bigint AS count FROM users GROUP BY role")
    users_by_role = {row["role"]: int(row["count"]) for row in role_rows}
    sessions_total = int(
        await pool.fetchval("SELECT COUNT(*) FROM chat_sessions WHERE is_deleted = FALSE") or 0
    )
    messages_total = int(await pool.fetchval("SELECT COUNT(*) FROM messages") or 0)

    tz = _tz()
    now_local = datetime.now(tz)
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = today_start_local.astimezone(timezone.utc)
    today_end = (today_start_local + timedelta(days=1)).astimezone(timezone.utc)
    usage_today = int(
        await pool.fetchval(
            "SELECT COUNT(*) FROM usage_logs WHERE created_at >= $1 AND created_at < $2",
            today_start,
            today_end,
        )
        or 0
    )
    recent = await pool.fetch("SELECT * FROM users ORDER BY created_at DESC LIMIT 5")

    start_date = now_local.date() - timedelta(days=6)
    start_utc = datetime.combine(start_date, time.min, tzinfo=tz).astimezone(timezone.utc)
    usage_rows = await pool.fetch(
        """
        SELECT created_at, tokens_prompt, tokens_completion
        FROM usage_logs
        WHERE created_at >= $1
        """,
        start_utc,
    )
    usage_map: dict[str, dict] = {}
    for row in usage_rows:
        day = row["created_at"].astimezone(tz).date().isoformat()
        item = usage_map.setdefault(day, {"requests": 0, "tokens": 0})
        item["requests"] += 1
        item["tokens"] += int(row["tokens_prompt"] or 0) + int(row["tokens_completion"] or 0)

    daily = []
    for offset in range(7):
        day = (start_date + timedelta(days=offset)).isoformat()
        row = usage_map.get(day)
        daily.append(
            {
                "day": day,
                "requests": int(row["requests"]) if row else 0,
                "tokens": int(row["tokens"]) if row else 0,
            }
        )

    return {
        "users_total": users_total,
        "users_by_role": users_by_role,
        "sessions_total": sessions_total,
        "messages_total": messages_total,
        "usage_today": usage_today,
        "recent_users": [user_public(row) for row in recent],
        "daily_usage": daily,
    }


@router.get("/keys", summary="查看全部 API Key（不返回明文）")
async def list_all_keys(_: CurrentUser = Depends(get_admin_user)) -> list[dict]:
    rows = await get_pool().fetch(
        """
        SELECT k.*, u.username FROM api_keys k
        JOIN users u ON u.id = k.user_id
        ORDER BY k.created_at DESC
        LIMIT 500
        """
    )
    return [{**api_key_public(row), "username": row["username"]} for row in rows]


@router.delete("/keys/{key_id}", response_model=MessageResponse, summary="吊销任意 API Key")
async def revoke_any_key(key_id: int, _: CurrentUser = Depends(get_admin_user)) -> dict:
    result = await get_pool().execute("DELETE FROM api_keys WHERE id = $1", key_id)
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="API Key 不存在")
    return {"message": "API Key 已吊销"}
