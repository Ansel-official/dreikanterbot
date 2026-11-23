"""asyncpg Record -> API JSON 的统一序列化。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _as_dict(record: Any) -> dict:
    return dict(record)


def user_public(record: Any) -> dict:
    data = _as_dict(record)
    return {
        "id": data["id"],
        "username": data["username"],
        "role": data["role"],
        "is_active": data["is_active"],
        "created_at": iso(data.get("created_at")),
        "last_login_at": iso(data.get("last_login_at")),
    }


def _attachments_public(value: Any, include_text: bool = False) -> list[dict]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = item.get("text") or ""
        data = {
            "name": str(item.get("name") or "附件"),
            "size": int(item.get("size") or 0),
            "mime": item.get("mime"),
            "text_chars": len(str(text)),
        }
        if include_text and text:
            data["text"] = str(text)
        result.append(data)
    return result


def message_public(record: Any, *, include_attachment_text: bool = False) -> dict:
    data = _as_dict(record)
    usage = data.get("usage")
    if isinstance(usage, str):
        try:
            usage = json.loads(usage)
        except json.JSONDecodeError:
            usage = None
    return {
        "id": data["id"],
        "session_id": data["session_id"],
        "role": data["role"],
        "content": data.get("content") or "",
        "reasoning": data.get("reasoning") or "",
        "mode": data.get("mode") or "chat",
        "attachments": _attachments_public(data.get("attachments"), include_attachment_text),
        "parent_id": data.get("parent_id"),
        "status": data.get("status") or "complete",
        "created_at": iso(data.get("created_at")),
        "usage": usage,
    }


def session_public(record: Any) -> dict:
    data = _as_dict(record)
    preview = data.get("last_message")
    if preview is not None:
        preview = str(preview)[:160]
    return {
        "id": data["id"],
        "title": data["title"],
        "created_at": iso(data.get("created_at")),
        "updated_at": iso(data.get("updated_at")),
        "message_count": int(data.get("message_count") or 0),
        "last_message": preview,
        "last_message_at": iso(data.get("last_message_at")),
        "is_deleted": bool(data.get("is_deleted", False)),
        "mode": data.get("mode") or "chat",
    }


def api_key_public(record: Any) -> dict:
    data = _as_dict(record)
    return {
        "id": data["id"],
        "name": data["name"],
        "key_prefix": data["key_prefix"],
        "is_active": data["is_active"],
        "created_at": iso(data.get("created_at")),
        "last_used_at": iso(data.get("last_used_at")),
    }
