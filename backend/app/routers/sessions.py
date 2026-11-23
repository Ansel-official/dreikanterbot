"""会话 CRUD、消息分页、JSON / Markdown 导出。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..database import get_pool
from ..deps import CurrentUser, get_current_user
from ..models import (
    MessagePage,
    MessageResponse,
    SessionCreate,
    SessionOut,
    SessionUpdate,
)
from ..serializers import message_public, session_public

router = APIRouter(prefix="/sessions", tags=["会话"])

SESSION_WITH_STATS = """
SELECT s.*,
       (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count,
       (SELECT m.content FROM messages m WHERE m.session_id = s.id
        ORDER BY m.id DESC LIMIT 1) AS last_message,
       (SELECT m.created_at FROM messages m WHERE m.session_id = s.id
        ORDER BY m.id DESC LIMIT 1) AS last_message_at
FROM chat_sessions s
WHERE s.id = $1 AND s.user_id = $2 {deleted_filter}
"""


async def _get_owned_session(pool, session_id: int, user_id: int, *, include_deleted: bool = False):
    sql = SESSION_WITH_STATS.format(deleted_filter="" if include_deleted else "AND s.is_deleted = FALSE")
    row = await pool.fetchrow(sql, session_id, user_id)
    if row is None:
        raise HTTPException(status_code=404, detail="会话不存在或无权限访问")
    return row


@router.get("", response_model=list[SessionOut], summary="会话列表（按最近更新排序）")
async def list_sessions(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    include_deleted: bool = Query(default=False, description="是否包含已软删除的会话"),
    user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT s.*,
               (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count,
               (SELECT m.content FROM messages m WHERE m.session_id = s.id
                ORDER BY m.id DESC LIMIT 1) AS last_message,
               (SELECT m.created_at FROM messages m WHERE m.session_id = s.id
                ORDER BY m.id DESC LIMIT 1) AS last_message_at
        FROM chat_sessions s
        WHERE s.user_id = $1 AND ($2::boolean OR s.is_deleted = FALSE)
        ORDER BY s.updated_at DESC
        LIMIT $3 OFFSET $4
        """,
        user.id,
        include_deleted,
        limit,
        offset,
    )
    return [session_public(row) for row in rows]


@router.post("", response_model=SessionOut, status_code=201, summary="新建会话")
async def create_session(
    payload: SessionCreate | None = None,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    title = (payload.title.strip() if payload and payload.title else "") or "新对话"
    mode = payload.mode if payload else "chat"
    row = await get_pool().fetchrow(
        """
        INSERT INTO chat_sessions (user_id, title, mode)
        VALUES ($1, $2, $3)
        RETURNING *, 0::bigint AS message_count, NULL::text AS last_message,
                  NULL::timestamptz AS last_message_at
        """,
        user.id,
        title[:200],
        mode,
    )
    return session_public(row)


@router.get("/export", summary="导出当前用户全部会话（json / markdown）")
async def export_all_sessions(
    format: Literal["json", "markdown", "md"] = Query(default="json"),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    pool = get_pool()
    sessions = await pool.fetch(
        """
        SELECT * FROM chat_sessions
        WHERE user_id = $1 AND is_deleted = FALSE
        ORDER BY created_at ASC
        """,
        user.id,
    )
    messages = await pool.fetch(
        """
        SELECT m.* FROM messages m
        JOIN chat_sessions s ON s.id = m.session_id
        WHERE s.user_id = $1 AND s.is_deleted = FALSE
        ORDER BY m.session_id ASC, m.id ASC
        """,
        user.id,
    )
    grouped: dict[int, list] = {}
    for message in messages:
        grouped.setdefault(message["session_id"], []).append(
            message_public(message, include_attachment_text=True)
        )

    payload = []
    for session in sessions:
        item = session_public(session)
        item.pop("last_message", None)
        item.pop("last_message_at", None)
        item["messages"] = grouped.get(session["id"], [])
        payload.append(item)

    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    if format == "json":
        body = json.dumps(
            {
                "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "user": user.username,
                "sessions": payload,
            },
            ensure_ascii=False,
            indent=2,
        )
        return Response(
            content=body,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="dreikanterbot-export-{today}.json"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    lines = [
        "# Dreikanterbot 全量导出",
        "",
        f"- 用户：{user.username}",
        f"- 导出时间：{datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}",
        f"- 会话数：{len(payload)}",
        "",
    ]
    for item in payload:
        lines.extend(
            [
                f"## {item['title']}（#{item['id']}）",
                "",
                f"创建时间：{item['created_at']}　最后更新：{item['updated_at']}",
                "",
            ]
        )
        for message in item["messages"]:
            role = "用户" if message["role"] == "user" else "助手"
            lines.extend([f"### {role} · {message['created_at']}", ""])
            if message.get("reasoning"):
                lines.extend(["> 深度思考：", "", f"> {message['reasoning']}", ""])
            for attachment in message.get("attachments", []):
                lines.append(f"附件：{attachment.get('name', '附件')}")
                if attachment.get("text"):
                    lines.extend(["", attachment["text"], ""])
            lines.extend([message["content"], ""])
        lines.extend(["---", ""])
    return Response(
        content="\n".join(lines),
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="dreikanterbot-export-{today}.md"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{session_id}", response_model=SessionOut, summary="会话详情")
async def get_session(session_id: int, user: CurrentUser = Depends(get_current_user)) -> dict:
    row = await _get_owned_session(get_pool(), session_id, user.id)
    return session_public(row)


@router.patch("/{session_id}", response_model=SessionOut, summary="重命名会话")
async def update_session(
    session_id: int,
    payload: SessionUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    pool = get_pool()
    await _get_owned_session(pool, session_id, user.id)
    await pool.execute(
        "UPDATE chat_sessions SET title = $1, updated_at = NOW() WHERE id = $2 AND user_id = $3",
        payload.title,
        session_id,
        user.id,
    )
    row = await _get_owned_session(pool, session_id, user.id)
    return session_public(row)


@router.delete("/{session_id}", response_model=MessageResponse, summary="软删除会话")
async def delete_session(session_id: int, user: CurrentUser = Depends(get_current_user)) -> dict:
    pool = get_pool()
    result = await pool.execute(
        """
        UPDATE chat_sessions SET is_deleted = TRUE, updated_at = NOW()
        WHERE id = $1 AND user_id = $2 AND is_deleted = FALSE
        """,
        session_id,
        user.id,
    )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="会话不存在或已删除")
    return {"message": "会话已删除（可在保留期内恢复）"}


@router.post("/{session_id}/restore", response_model=SessionOut, summary="恢复软删除会话")
async def restore_session(session_id: int, user: CurrentUser = Depends(get_current_user)) -> dict:
    pool = get_pool()
    row = await _get_owned_session(pool, session_id, user.id, include_deleted=True)
    if row["is_deleted"]:
        await pool.execute(
            "UPDATE chat_sessions SET is_deleted = FALSE, updated_at = NOW() WHERE id = $1 AND user_id = $2",
            session_id,
            user.id,
        )
    row = await _get_owned_session(pool, session_id, user.id, include_deleted=True)
    return session_public(row)


@router.get("/{session_id}/messages", response_model=MessagePage, summary="消息历史（游标分页）")
async def list_messages(
    session_id: int,
    before_id: int | None = Query(default=None, ge=1, description="返回 id 小于该值的消息，用于向上翻页"),
    limit: int = Query(default=50, ge=1, le=200),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    pool = get_pool()
    await _get_owned_session(pool, session_id, user.id)

    if before_id is None:
        rows = await pool.fetch(
            "SELECT * FROM messages WHERE session_id = $1 ORDER BY id DESC LIMIT $2",
            session_id,
            limit + 1,
        )
    else:
        rows = await pool.fetch(
            "SELECT * FROM messages WHERE session_id = $1 AND id < $2 ORDER BY id DESC LIMIT $3",
            session_id,
            before_id,
            limit + 1,
        )

    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [message_public(row) for row in reversed(rows)]
    return {
        "items": items,
        "has_more": has_more,
        "next_before_id": items[0]["id"] if has_more and items else None,
    }


@router.get("/{session_id}/export", summary="导出单个会话（json / markdown）")
async def export_session(
    session_id: int,
    format: Literal["json", "markdown", "md"] = Query(default="json"),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    pool = get_pool()
    session = await _get_owned_session(pool, session_id, user.id)
    messages = await pool.fetch(
        "SELECT * FROM messages WHERE session_id = $1 ORDER BY id ASC",
        session_id,
    )
    items = [message_public(row, include_attachment_text=True) for row in messages]
    conversation = {
        "exported_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "session": {
            "id": session["id"],
            "title": session["title"],
            "created_at": session["created_at"].isoformat(),
            "updated_at": session["updated_at"].isoformat(),
        },
        "messages": items,
    }
    filename_base = f"dreikanterbot-session-{session_id}"

    if format == "json":
        return Response(
            content=json.dumps(conversation, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename_base}.json"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    lines = [
        f"# {session['title']}",
        "",
        f"- 会话 ID：{session_id}",
        f"- 创建时间：{session['created_at'].isoformat()}",
        f"- 导出时间：{conversation['exported_at']}",
        "",
        "---",
        "",
    ]
    for message in items:
        role = "用户" if message["role"] == "user" else "助手"
        lines.extend([f"## {role}", "", f"*{message['created_at']}*", ""])
        if message.get("reasoning"):
            lines.extend(["> 深度思考：", "", f"> {message['reasoning']}", ""])
        for attachment in message.get("attachments", []):
            lines.append(f"附件：{attachment.get('name', '附件')}")
            if attachment.get("text"):
                lines.extend(["", attachment["text"], ""])
        lines.extend([message["content"], "", "---", ""])
    return Response(
        content="\n".join(lines),
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="{filename_base}.md"',
            "X-Content-Type-Options": "nosniff",
        },
    )
