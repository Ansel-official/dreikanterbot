"""DeepSeek / 通用对话 JSON 导入解析器。

支持常见导出结构（字段名做宽松匹配）：
- 本应用导出的 {"sessions":[{"title","mode","messages":[...]}]}
- {"conversations":[{"title","messages":[{"role","content"}]}]}
- {"chat_sessions":[{"name","chat_messages":[...]}]}
- 单个 {"title","messages":[...]} / 顶层消息数组
- content 为字符串，或 [{"type":"text","text":"..."}] 块数组
- reasoning_content / reasoning / thinking 字段会作为思考内容保留
"""
from __future__ import annotations

import json
from typing import Any

MAX_SESSIONS = 100
MAX_MESSAGES = 5000


class ConversationImportError(ValueError):
    pass


_ROLE_MAP = {
    "user": "user",
    "human": "user",
    "me": "user",
    "assistant": "assistant",
    "ai": "assistant",
    "bot": "assistant",
    "model": "assistant",
}
_CONVERSATION_KEYS = ("sessions", "conversations", "chats", "chat_sessions", "data", "items")
_MESSAGE_KEYS = ("messages", "chat_messages", "history", "conversation", "turns")
_TITLE_KEYS = ("title", "name", "topic", "subject", "conversation_title")
_REASONING_KEYS = ("reasoning_content", "reasoning", "thinking")


def _text_of(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in ("text", "content", "message", "value"):
            if key in value:
                return _text_of(value[key])
        return ""
    if isinstance(value, list):
        parts = []
        for item in value:
            text = _text_of(item)
            if text:
                parts.append(text)
        return "\n".join(parts)
    return ""


def _role_of(value: Any, default: str = "") -> str:
    raw = str(value or "").strip().lower()
    if raw in _ROLE_MAP:
        return _ROLE_MAP[raw]
    if raw in {"system", "developer"}:
        return "system"
    return default


def _reasoning_of(message: dict) -> str:
    for key in _REASONING_KEYS:
        if key in message:
            text = _text_of(message.get(key))
            if text.strip():
                return text.strip()
    return ""


def _looks_like_messages(value: Any) -> bool:
    if not isinstance(value, list) or not value:
        return False
    dicts = [item for item in value if isinstance(item, dict)]
    if len(dicts) < max(1, len(value) // 2):
        return False
    return any(
        any(key in item for key in ("role", "from", "author")) for item in dicts
    )


def _normalise_messages(raw: Any) -> list[dict]:
    if _looks_like_messages(raw):
        candidates = raw
    elif isinstance(raw, dict):
        candidates = []
        for key in _MESSAGE_KEYS:
            value = raw.get(key)
            if _looks_like_messages(value):
                candidates = value
                break
    else:
        candidates = []
    messages: list[dict] = []
    for index, item in enumerate(candidates):
        if not isinstance(item, dict):
            continue
        role = _role_of(item.get("role") or item.get("from") or item.get("author"))
        if role not in {"user", "assistant"}:
            continue
        content = _text_of(item.get("content") or item.get("text") or item.get("message")).strip()
        reasoning = _reasoning_of(item)
        if not content and not reasoning:
            continue
        # 官方导出有时用 message_id / id；这里不依赖，按出现顺序导入
        messages.append(
            {
                "role": role,
                "content": content or "（原对话中这条回复为空）",
                "reasoning": reasoning,
                "source_index": index,
            }
        )
        if len(messages) >= MAX_MESSAGES:
            break
    return messages


def _conversation_of(item: Any) -> dict | None:
    if not isinstance(item, dict):
        return None
    # 有些导出把消息放在 data / conversation 子对象里
    messages = _normalise_messages(item)
    if not messages and isinstance(item.get("conversation"), dict):
        messages = _normalise_messages(item["conversation"])
    if not messages:
        return None
    title = ""
    for key in _TITLE_KEYS:
        if item.get(key):
            title = _text_of(item[key]).strip()
            break
    mode = "reasoner" if any(message["reasoning"] for message in messages) else "chat"
    return {"title": title, "messages": messages, "mode": mode}


def parse_conversations(payload: Any) -> list[dict]:
    """把未知结构的 JSON 尽量还原为 [{'title','messages','mode'}]。"""
    conversations: list[dict] = []

    def collect(value: Any) -> None:
        if len(conversations) >= MAX_SESSIONS:
            return
        if isinstance(value, list):
            if _looks_like_messages(value):
                normalized = _normalise_messages(value)
                if normalized:
                    conversations.append(
                        {
                            "title": "",
                            "messages": normalized,
                            "mode": "reasoner"
                            if any(message["reasoning"] for message in normalized)
                            else "chat",
                        }
                    )
                return
            for item in value:
                collect(item)
            return
        if not isinstance(value, dict):
            return

        single = _conversation_of(value)
        if single:
            conversations.append(single)
            return

        for key in _CONVERSATION_KEYS:
            if key in value:
                collect(value[key])
                if conversations:
                    return
        # 最后尝试遍历所有值，兼容 "data": {"data": [...]} 等包装
        for nested in value.values():
            if isinstance(nested, (dict, list)):
                collect(nested)
                if conversations:
                    return

    collect(payload)
    if not conversations:
        raise ConversationImportError("没有识别到对话消息，请上传 DeepSeek 官方导出的 JSON")

    # 去掉空会话并重新生成标题
    result = []
    for conversation in conversations[:MAX_SESSIONS]:
        messages = conversation["messages"][:MAX_MESSAGES]
        if not messages:
            continue
        title = (conversation.get("title") or "").strip()
        if not title:
            first_user = next((m["content"] for m in messages if m["role"] == "user"), "")
            title = " ".join(first_user.split())[:40] or "导入的 DeepSeek 对话"
        result.append(
            {
                "title": title[:200],
                "mode": conversation.get("mode") or "chat",
                "messages": messages,
            }
        )
    if not result:
        raise ConversationImportError("对话中没有可导入的消息")
    return result


def parse_export_bytes(data: bytes) -> list[dict]:
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConversationImportError("文件不是有效的 UTF-8 JSON") from exc
    return parse_conversations(payload)
