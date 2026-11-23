"""公共依赖：JWT / API Key 鉴权、管理员校验、客户端 IP。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .database import get_pool
from .security import (
    TokenError,
    decode_access_token,
    hash_api_key,
    is_api_key,
)
from .services.rate_limit import is_token_blacklisted

bearer_scheme = HTTPBearer(
    auto_error=False,
    description="登录接口返回的 JWT，或创建 API Key 时返回的 sk-chat- 密钥",
)


@dataclass
class CurrentUser:
    id: int
    username: str
    role: str
    is_active: bool
    auth_type: str = "jwt"
    api_key_id: int | None = None
    jti: str | None = None
    token_expires_at: datetime | None = None
    token_version: int | None = None


def _unauthorized(detail: str = "未登录或登录已过期") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def resolve_user_from_token(token: str) -> CurrentUser:
    """同时支持 JWT 与 API Key；HTTP 和 WebSocket 共用。"""
    if not token:
        raise _unauthorized()

    pool = get_pool()

    if is_api_key(token):
        row = await pool.fetchrow(
            """
            SELECT k.id AS api_key_id, u.id, u.username, u.role, u.is_active
            FROM api_keys k
            JOIN users u ON u.id = k.user_id
            WHERE k.key_hash = $1 AND k.is_active = TRUE
            """,
            hash_api_key(token),
        )
        if row is None:
            raise _unauthorized("API Key 无效或已被吊销")
        if not row["is_active"]:
            raise _unauthorized("账号已被禁用")
        await pool.execute(
            """
            UPDATE api_keys SET last_used_at = NOW()
            WHERE id = $1 AND (last_used_at IS NULL OR last_used_at < NOW() - INTERVAL '60 seconds')
            """,
            row["api_key_id"],
        )
        return CurrentUser(
            id=row["id"],
            username=row["username"],
            role=row["role"],
            is_active=bool(row["is_active"]),
            auth_type="api_key",
            api_key_id=row["api_key_id"],
        )

    try:
        payload = decode_access_token(token)
    except TokenError as exc:
        raise _unauthorized(str(exc)) from exc

    jti = str(payload.get("jti") or "")
    if not jti or await is_token_blacklisted(jti):
        raise _unauthorized("登录已失效，请重新登录")

    user_id = int(payload["sub"])
    row = await pool.fetchrow(
        "SELECT id, username, role, is_active, token_version FROM users WHERE id = $1",
        user_id,
    )
    if row is None:
        raise _unauthorized("账号不存在")
    if not row["is_active"]:
        raise _unauthorized("账号已被管理员禁用")
    if int(row["token_version"]) != int(payload["ver"]):
        raise _unauthorized("登录状态已失效，请重新登录")

    return CurrentUser(
        id=row["id"],
        username=row["username"],
        role=row["role"],
        is_active=bool(row["is_active"]),
        auth_type="jwt",
        jti=jti,
        token_expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc),
        token_version=int(row["token_version"]),
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if credentials is None or not credentials.credentials:
        raise _unauthorized()
    return await resolve_user_from_token(credentials.credentials)


async def get_admin_user(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def client_ip(request: Request) -> str:
    """仅在请求经过受信 Nginx / Cloudflare 时使用；源站应只允许 Cloudflare 回源。"""
    for header in ("cf-connecting-ip", "x-real-ip", "x-forwarded-for"):
        value = request.headers.get(header)
        if value:
            return value.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"
