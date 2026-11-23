"""PostgreSQL 连接池、自动建表与管理员引导。

设计要点：
- 后端本身无状态，所有会话/消息/用户数据均落 PostgreSQL；
- 建表全部使用 IF NOT EXISTS，可安全地在每次启动时执行；
- 额外字段（messages.status / messages.usage / users.last_login_at）通过
  ALTER TABLE ... IF NOT EXISTS 兼容已有数据库的平滑升级。
"""
from __future__ import annotations

import json
import logging

import asyncpg

from .config import settings
from .security import PasswordPolicyError, hash_password, validate_password_policy

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id            BIGSERIAL PRIMARY KEY,
    username      VARCHAR(64) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          VARCHAR(16) NOT NULL DEFAULT 'member'
                  CHECK (role IN ('admin', 'member', 'guest')),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    token_version INTEGER NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title      VARCHAR(200) NOT NULL DEFAULT '新对话',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS messages (
    id         BIGSERIAL PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role       VARCHAR(16) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content    TEXT NOT NULL DEFAULT '',
    parent_id  BIGINT REFERENCES messages(id) ON DELETE SET NULL,
    status     VARCHAR(16) NOT NULL DEFAULT 'complete',
    usage      JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS api_keys (
    id           BIGSERIAL PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         VARCHAR(100) NOT NULL,
    key_prefix   VARCHAR(24) NOT NULL,
    key_hash     TEXT NOT NULL UNIQUE,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS usage_logs (
    id                BIGSERIAL PRIMARY KEY,
    user_id           BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind              VARCHAR(16) NOT NULL,
    tokens_prompt     INTEGER NOT NULL DEFAULT 0,
    tokens_completion INTEGER NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_updated
    ON chat_sessions (user_id, updated_at DESC) WHERE is_deleted = FALSE;
CREATE INDEX IF NOT EXISTS idx_messages_session_id
    ON messages (session_id, id);
CREATE INDEX IF NOT EXISTS idx_api_keys_user
    ON api_keys (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_user_created
    ON usage_logs (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_created
    ON usage_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_users_role
    ON users (role);

-- 兼容旧版本的平滑升级
ALTER TABLE messages ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'complete';
ALTER TABLE messages ADD COLUMN IF NOT EXISTS usage JSONB;
ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();
"""

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """让 asyncpg 自动把 JSON/JSONB 转成 Python 对象，而不是字符串。"""
    for type_name in ("json", "jsonb"):
        await conn.set_type_codec(
            type_name,
            encoder=json.dumps,
            decoder=json.loads,
            schema="pg_catalog",
        )


async def init_db() -> None:
    global _pool
    if _pool is not None:
        return

    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
        command_timeout=60,
        init=_init_connection,
    )
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA_SQL)
        await _seed_admin(conn)
    logger.info("PostgreSQL 连接池已就绪（池大小 %s-%s）", settings.db_pool_min_size, settings.db_pool_max_size)


async def _seed_admin(conn: asyncpg.Connection) -> None:
    """首次启动时按环境变量创建管理员；不会覆盖已存在的管理员。"""
    has_admin = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM users WHERE role = 'admin' AND is_active = TRUE)"
    )
    if has_admin:
        return
    if not settings.admin_password:
        logger.warning(
            "users 表尚无管理员，但 ADMIN_PASSWORD 为空。"
            "请设置 ADMIN_PASSWORD 后重启，或使用 /api/auth/bootstrap 创建管理员。"
        )
        return

    username = settings.admin_username.strip().lower()
    if not username:
        logger.warning("ADMIN_USERNAME 为空，跳过管理员初始化")
        return
    try:
        validate_password_policy(settings.admin_password)
    except PasswordPolicyError as exc:
        raise RuntimeError(f"ADMIN_PASSWORD 不符合密码策略：{exc}") from exc

    existing = await conn.fetchrow("SELECT id FROM users WHERE username = $1", username)
    if existing:
        await conn.execute(
            "UPDATE users SET role = 'admin', is_active = TRUE, updated_at = NOW() WHERE id = $1",
            existing["id"],
        )
        logger.warning("已存在用户 %s，已将其提升为管理员（请尽快修改密码）", username)
        return

    await conn.execute(
        """
        INSERT INTO users (username, password_hash, role, is_active)
        VALUES ($1, $2, 'admin', TRUE)
        """,
        username,
        hash_password(settings.admin_password),
    )
    logger.warning("已根据环境变量创建管理员账号：%s（请登录后立即修改密码）", username)


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("数据库连接池尚未初始化")
    return _pool


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def db_healthy() -> bool:
    try:
        async with get_pool().acquire() as conn:
            return await conn.fetchval("SELECT 1") == 1
    except Exception:  # noqa: BLE001 - 健康检查不应抛出
        return False
