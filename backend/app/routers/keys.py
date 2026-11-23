"""用户自助管理 API Key（供外部系统 / 脚本调用 REST 接口）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..database import get_pool
from ..deps import CurrentUser, get_current_user
from ..models import ApiKeyCreate, ApiKeyCreated, ApiKeyOut, MessageResponse
from ..security import generate_api_key
from ..serializers import api_key_public

router = APIRouter(prefix="/keys", tags=["API Key"])

MAX_ACTIVE_KEYS = 10


@router.get("", response_model=list[ApiKeyOut], summary="我的 API Key 列表")
async def list_keys(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    rows = await get_pool().fetch(
        "SELECT * FROM api_keys WHERE user_id = $1 ORDER BY created_at DESC",
        user.id,
    )
    return [api_key_public(row) for row in rows]


@router.post("", response_model=ApiKeyCreated, status_code=201, summary="创建 API Key（明文只显示一次）")
async def create_key(
    payload: ApiKeyCreate,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    pool = get_pool()
    active = int(
        await pool.fetchval(
            "SELECT COUNT(*) FROM api_keys WHERE user_id = $1 AND is_active = TRUE",
            user.id,
        )
        or 0
    )
    if active >= MAX_ACTIVE_KEYS:
        raise HTTPException(
            status_code=400,
            detail=f"每个账号最多同时拥有 {MAX_ACTIVE_KEYS} 个有效 API Key，请先吊销旧的密钥",
        )

    plaintext, prefix, key_hash = generate_api_key()
    row = await pool.fetchrow(
        """
        INSERT INTO api_keys (user_id, name, key_prefix, key_hash)
        VALUES ($1, $2, $3, $4)
        RETURNING *
        """,
        user.id,
        payload.name,
        prefix,
        key_hash,
    )
    return {**api_key_public(row), "key": plaintext}


@router.delete("/{key_id}", response_model=MessageResponse, summary="吊销 API Key")
async def revoke_key(key_id: int, user: CurrentUser = Depends(get_current_user)) -> dict:
    result = await get_pool().execute(
        "UPDATE api_keys SET is_active = FALSE WHERE id = $1 AND user_id = $2 AND is_active = TRUE",
        key_id,
        user.id,
    )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="API Key 不存在或已吊销")
    return {"message": "API Key 已吊销，立即生效"}
