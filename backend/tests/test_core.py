"""不依赖数据库的核心逻辑测试。"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.models import RegisterRequest
from app.security import (
    PasswordPolicyError,
    create_access_token,
    decode_access_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    validate_password_policy,
    verify_password,
)
from app.serializers import message_public, session_public, user_public
from app.services.deepseek import build_context, deepseek_configured, trim_history
from app.services.rate_limit import (
    QuotaExceeded,
    _local_counts,
    consume_daily_quota,
    peek_daily_quota,
    role_limit,
)


def test_password_hash_and_policy() -> None:
    hashed = hash_password("Hello-123456")
    assert verify_password("Hello-123456", hashed)
    assert not verify_password("wrong-password", hashed)
    with pytest.raises(PasswordPolicyError):
        validate_password_policy("short")
    with pytest.raises(PasswordPolicyError):
        validate_password_policy("onlyletters")
    with pytest.raises(Exception):
        RegisterRequest(username="alice", password="onlyletters", role="member")


def test_jwt_contains_version_and_expiry() -> None:
    token, expires, jti = create_access_token(7, "member", token_version=3)
    payload = decode_access_token(token)
    assert payload["sub"] == "7"
    assert payload["role"] == "member"
    assert payload["ver"] == 3
    assert payload["jti"] == jti
    assert abs((expires - datetime.now(timezone.utc)).days - 30) <= 1


def test_api_key_is_hashed_not_recoverable() -> None:
    plaintext, prefix, digest = generate_api_key()
    assert plaintext.startswith("sk-chat-")
    assert plaintext.startswith(prefix)
    assert hash_api_key(plaintext) == digest
    assert len(digest) == 64
    assert plaintext not in digest


def test_daily_quota_local_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "guest_daily_limit", 2)
    asyncio.run(_quota_tests())


async def _quota_tests() -> None:
    _local_counts.clear()
    admin_quota = await consume_daily_quota(9001, "admin")
    assert admin_quota.limit is None
    assert admin_quota.remaining is None
    await consume_daily_quota(9002, "guest")
    await consume_daily_quota(9002, "guest")
    with pytest.raises(QuotaExceeded):
        await consume_daily_quota(9002, "guest")
    quota = await peek_daily_quota(9002, "guest")
    assert quota.used == 3
    assert quota.remaining == 0
    assert role_limit("member") == 1000
    assert role_limit("guest") == 2


def test_context_trimming_keeps_recent_messages() -> None:
    history = [
        {"role": "user", "content": "a" * 100},
        {"role": "assistant", "content": "b" * 100},
        {"role": "user", "content": "current question"},
    ]
    trimmed, dropped = trim_history(history, 150)
    assert len(trimmed) == 2
    assert trimmed[-1]["content"] == "current question"
    assert dropped == 1
    context = build_context(history)
    assert context.messages[0]["role"] == "system"
    assert context.messages[-1]["role"] == "user"


def test_serializers() -> None:
    record = {
        "id": 1,
        "session_id": 2,
        "role": "assistant",
        "content": "hi",
        "parent_id": 1,
        "status": "complete",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "usage": {"total_tokens": 3},
    }
    public = message_public(record)
    assert public["created_at"].endswith("Z")
    assert public["usage"]["total_tokens"] == 3
    session = session_public(
        {
            "id": 2,
            "title": "t",
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "message_count": 4,
            "last_message": "x" * 300,
            "is_deleted": False,
        }
    )
    assert len(session["last_message"]) == 160
    user = user_public(
        {
            "id": 1,
            "username": "alice",
            "role": "member",
            "is_active": True,
            "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "last_login_at": None,
        }
    )
    assert user["username"] == "alice"


def test_openapi_and_health_without_database() -> None:
    from app.main import app

    schema = app.openapi()
    assert len(schema["paths"]) >= 26
    assert "/api/auth/login" in schema["paths"]
    assert "/api/admin/users" in schema["paths"]

    client = TestClient(app)
    version = client.get("/api/version")
    assert version.status_code == 200
    assert version.headers["x-content-type-options"] == "nosniff"
    health = client.get("/api/health")
    assert health.status_code == 503
    assert health.json()["database"] is False


def test_placeholder_deepseek_key_is_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-please-replace-me")
    assert deepseek_configured() is False
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    assert deepseek_configured() is False
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-real-looking-key")
    assert deepseek_configured() is True
