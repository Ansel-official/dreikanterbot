"""导入 DeepSeek 官方/通用 JSON 对话，导入后可直接继续聊天。"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from ..config import settings
from ..database import get_pool
from ..deps import CurrentUser, client_ip, get_current_user
from ..models import ImportResponse
from ..services.conversation_import import (
    ConversationImportError,
    parse_export_bytes,
)
from ..services.rate_limit import RateLimitExceeded, enforce_ip_rate

router = APIRouter(prefix="/imports", tags=["导入"])
logger = logging.getLogger(__name__)


@router.post(
    "/deepseek",
    response_model=ImportResponse,
    summary="导入 DeepSeek 官方对话 JSON，返回可继续聊天的会话",
)
async def import_deepseek(
    request: Request,
    file: UploadFile = File(..., description="DeepSeek 导出的 JSON 文件"),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        await enforce_ip_rate("import", client_ip(request), limit=5, window_seconds=60)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="导入过于频繁，请稍后再试",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc

    data = await file.read(settings.max_import_bytes + 1)
    filename = file.filename or "deepseek-export.json"
    await file.close()
    if len(data) > settings.max_import_bytes:
        raise HTTPException(status_code=413, detail=f"导入文件不能超过 {settings.max_import_mb}MB")
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")

    try:
        conversations = await asyncio.to_thread(parse_export_bytes, data)
    except ConversationImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("对话导入解析失败 user=%s name=%s", user.id, filename)
        raise HTTPException(status_code=500, detail="对话导入失败") from exc

    pool = get_pool()
    session_ids: list[int] = []
    imported_messages = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for conversation in conversations:
                mode = conversation.get("mode") or "chat"
                session_row = await conn.fetchrow(
                    """
                    INSERT INTO chat_sessions (user_id, title, mode)
                    VALUES ($1, $2, $3)
                    RETURNING id
                    """,
                    user.id,
                    conversation["title"][:200],
                    mode,
                )
                session_id = session_row["id"]
                session_ids.append(session_id)
                parent_id = None
                for message in conversation["messages"]:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO messages
                            (session_id, role, content, reasoning, mode, parent_id, status)
                        VALUES ($1, $2, $3, $4, $5, $6, 'complete')
                        RETURNING id
                        """,
                        session_id,
                        message["role"],
                        message["content"],
                        message.get("reasoning") or "",
                        mode,
                        parent_id,
                    )
                    parent_id = row["id"]
                    imported_messages += 1
                await conn.execute(
                    "UPDATE chat_sessions SET updated_at = NOW() WHERE id = $1",
                    session_id,
                )

    logger.info(
        "对话导入完成 user=%s sessions=%s messages=%s",
        user.id,
        len(session_ids),
        imported_messages,
    )
    return {
        "imported_sessions": len(session_ids),
        "imported_messages": imported_messages,
        "session_ids": session_ids,
        "continue_session_id": session_ids[-1] if session_ids else None,
        "skipped_messages": 0,
    }
