"""PostgreSQL + Redis 集成测试。

本地默认跳过；GitHub Actions 会启动 postgres/redis service 并设置：
    TEST_DATABASE_URL, TEST_REDIS_URL
需要可丢弃的测试数据库（名称包含 test），测试会先 DROP 所有业务表。
"""
from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.routers import chat_ws
from app.services.deepseek import StreamEvent

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION") != "1",
    reason="需要 TEST_DATABASE_URL 指向可丢弃的 PostgreSQL 测试库",
)


@pytest.fixture(scope="module")
def client():
    if "test" not in settings.database_url.lower():
        pytest.skip("TEST_DATABASE_URL 必须指向名称包含 test 的数据库")

    async def reset_database() -> None:
        conn = await asyncpg.connect(settings.database_url)
        try:
            await conn.execute(
                "DROP TABLE IF EXISTS usage_logs, api_keys, messages, chat_sessions, users CASCADE"
            )
        finally:
            await conn.close()

    asyncio.run(reset_database())
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def admin_headers(client: TestClient) -> dict:
    token = login(
        client,
        os.environ.get("ADMIN_USERNAME", "admin"),
        os.environ.get("ADMIN_PASSWORD", "Test-Admin-123456"),
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def member(client: TestClient, admin_headers: dict) -> dict:
    username = f"pytest_{uuid.uuid4().hex[:8]}"
    password = "Member-123456"
    response = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={"username": username, "password": password, "role": "member"},
    )
    assert response.status_code == 201, response.text
    user = response.json()
    return {"id": user["id"], "username": username, "password": password}


@pytest.fixture(scope="module")
def member_headers(client: TestClient, member: dict) -> dict:
    token = login(client, member["username"], member["password"])
    return {"Authorization": f"Bearer {token}"}


def test_admin_user_management(client: TestClient, admin_headers: dict, member: dict) -> None:
    users = client.get("/api/admin/users", headers=admin_headers)
    assert users.status_code == 200
    assert users.json()["total"] >= 2
    assert any(item["username"] == member["username"] for item in users.json()["items"])

    stats = client.get("/api/admin/stats", headers=admin_headers)
    assert stats.status_code == 200
    assert stats.json()["users_total"] >= 2
    assert len(stats.json()["daily_usage"]) == 7

    forbidden = client.get("/api/admin/users", headers={"Authorization": "Bearer invalid"})
    assert forbidden.status_code == 401


def test_websocket_chat_persists_and_exports(
    client: TestClient, member_headers: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    create = client.post("/api/sessions", headers=member_headers)
    assert create.status_code == 201, create.text
    session_id = create.json()["id"]

    async def fake_stream(history):
        assert history[-1]["role"] == "user"
        yield StreamEvent(content="**你好**，")
        yield StreamEvent(content="这是集成测试回复。")
        yield StreamEvent(
            usage={"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}
        )

    monkeypatch.setattr(chat_ws, "stream_completion", fake_stream)

    token = member_headers["Authorization"].split(" ", 1)[1]
    events: list[dict] = []
    with client.websocket_connect(f"/ws/chat?token={token}") as websocket:
        ready = websocket.receive_json()
        assert ready["type"] == "ready"
        websocket.send_json(
            {
                "type": "chat",
                "session_id": session_id,
                "content": "请回复一条测试消息",
                "client_id": "pytest-client",
            }
        )
        while True:
            event = websocket.receive_json()
            events.append(event)
            if event["type"] == "assistant_done":
                break
            if event["type"] == "error":
                pytest.fail(f"WebSocket 返回错误：{event}")

    deltas = "".join(event["content"] for event in events if event["type"] == "delta")
    assert deltas == "**你好**，这是集成测试回复。"
    done = events[-1]
    assert done["status"] == "complete"
    assert done["message"]["content"] == deltas
    assert done["message"]["usage"]["total_tokens"] == 20

    messages = client.get(f"/api/sessions/{session_id}/messages", headers=member_headers)
    assert messages.status_code == 200
    items = messages.json()["items"]
    assert [item["role"] for item in items] == ["user", "assistant"]
    assert items[1]["content"] == deltas
    assert items[1]["status"] == "complete"

    exported = client.get(f"/api/sessions/{session_id}/export?format=json", headers=member_headers)
    assert exported.status_code == 200
    assert exported.json()["session"]["id"] == session_id
    assert exported.json()["messages"][1]["content"] == deltas
    markdown = client.get(
        f"/api/sessions/{session_id}/export?format=markdown", headers=member_headers
    )
    assert markdown.status_code == 200
    assert "这是集成测试回复" in markdown.text

    renamed = client.patch(
        f"/api/sessions/{session_id}",
        headers=member_headers,
        json={"title": "集成测试会话"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "集成测试会话"

    deleted = client.delete(f"/api/sessions/{session_id}", headers=member_headers)
    assert deleted.status_code == 200
    hidden = client.get("/api/sessions", headers=member_headers)
    assert all(item["id"] != session_id for item in hidden.json())
    restored = client.post(f"/api/sessions/{session_id}/restore", headers=member_headers)
    assert restored.status_code == 200
    assert restored.json()["title"] == "集成测试会话"


def test_api_key_lifecycle(client: TestClient, member_headers: dict) -> None:
    created = client.post("/api/keys", headers=member_headers, json={"name": "pytest-key"})
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["key"].startswith("sk-chat-")
    key_id = payload["id"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {payload['key']}"})
    assert me.status_code == 200

    keys = client.get("/api/keys", headers=member_headers)
    assert keys.status_code == 200
    assert any(item["id"] == key_id for item in keys.json())

    revoked = client.delete(f"/api/keys/{key_id}", headers=member_headers)
    assert revoked.status_code == 200
    after = client.get("/api/auth/me", headers={"Authorization": f"Bearer {payload['key']}"})
    assert after.status_code == 401
