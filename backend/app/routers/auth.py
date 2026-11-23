"""认证：登录、登出、管理员创建账号、首次引导、改密。"""
from __future__ import annotations

import asyncio
import logging

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status

from ..config import settings
from ..database import get_pool
from ..deps import CurrentUser, client_ip, get_current_user
from ..models import (
    BootstrapRequest,
    LoginRequest,
    MessageResponse,
    PasswordChange,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from ..security import (
    PasswordPolicyError,
    create_access_token,
    hash_password,
    validate_password_policy,
    verify_password,
)
from ..serializers import user_public
from ..services.rate_limit import (
    RateLimitExceeded,
    blacklist_token,
    enforce_ip_rate,
)

router = APIRouter(prefix="/auth", tags=["认证"])
logger = logging.getLogger(__name__)

# 用于"用户不存在"时仍执行一次 bcrypt，避免通过响应时间枚举用户名。
_dummy_hash: str | None = None


def _get_dummy_hash() -> str:
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("dummy-password-123")
    return _dummy_hash


def _token_payload(row) -> dict:
    token, expires_at, _ = create_access_token(
        row["id"], row["role"], int(row["token_version"] or 0)
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at,
        "user": user_public(row),
    }


@router.post("/login", response_model=TokenResponse, summary="账号密码登录")
async def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    username = payload.username.strip().lower()
    ip = client_ip(request)
    try:
        # 办公网可能共用出口 IP：IP 维度放宽，账号维度收紧，避免误伤同事登录
        await enforce_ip_rate("login-ip", ip, limit=60, window_seconds=300)
        await enforce_ip_rate("login-user", f"{ip}:{username}", limit=10, window_seconds=300)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录尝试过于频繁，请 5 分钟后再试",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc

    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM users WHERE username = $1", username)
    stored_hash = row["password_hash"] if row else await asyncio.to_thread(_get_dummy_hash)
    password_ok = await asyncio.to_thread(verify_password, payload.password, stored_hash)
    if row is None or not password_ok:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not row["is_active"]:
        raise HTTPException(status_code=403, detail="账号已被管理员禁用")

    updated = await pool.fetchrow(
        "UPDATE users SET last_login_at = NOW() WHERE id = $1 RETURNING *",
        row["id"],
    )
    response.headers["Cache-Control"] = "no-store"
    return _token_payload(updated or row)


@router.post(
    "/register",
    response_model=UserOut,
    status_code=201,
    summary="管理员创建账号",
)
async def register(
    payload: RegisterRequest,
    admin: CurrentUser = Depends(get_current_user),
) -> dict:
    if admin.role != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可以创建账号")
    try:
        password_hash = await asyncio.to_thread(hash_password, payload.password)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    pool = get_pool()
    try:
        row = await pool.fetchrow(
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


@router.post("/bootstrap", response_model=TokenResponse, summary="系统初始化：创建第一个管理员")
async def bootstrap(
    payload: BootstrapRequest,
    x_bootstrap_token: str | None = Header(default=None),
) -> dict:
    """仅当 users 表为空时可用；部署脚本也可以用 ADMIN_PASSWORD 自动完成。"""
    if not settings.allow_bootstrap:
        raise HTTPException(status_code=403, detail="系统未开启引导接口")
    if settings.bootstrap_token and x_bootstrap_token != settings.bootstrap_token:
        raise HTTPException(status_code=403, detail="引导令牌无效")

    password_hash = await asyncio.to_thread(hash_password, payload.password)
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # 事务级 advisory lock，避免两个初始化请求同时创建管理员
            await conn.execute("SELECT pg_advisory_xact_lock(20240101)")
            count = await conn.fetchval("SELECT COUNT(*) FROM users")
            if count:
                raise HTTPException(status_code=409, detail="系统已初始化，请使用登录接口")
            row = await conn.fetchrow(
                """
                INSERT INTO users (username, password_hash, role, is_active)
                VALUES ($1, $2, 'admin', TRUE)
                RETURNING *
                """,
                payload.username,
                password_hash,
            )
    logger.warning("通过 /auth/bootstrap 创建了初始管理员：%s", row["username"])
    return _token_payload(row)


@router.get("/me", response_model=UserOut, summary="当前登录用户")
async def me(user: CurrentUser = Depends(get_current_user)) -> dict:
    row = await get_pool().fetchrow("SELECT * FROM users WHERE id = $1", user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user_public(row)


@router.post("/logout", response_model=MessageResponse, summary="登出（JWT 加入黑名单）")
async def logout(user: CurrentUser = Depends(get_current_user)) -> dict:
    if user.auth_type == "api_key":
        raise HTTPException(status_code=400, detail="API Key 不需要登出，请在密钥管理中吊销")
    if not user.jti or not user.token_expires_at:
        raise HTTPException(status_code=400, detail="当前凭证不支持登出")
    await blacklist_token(user.jti, user.token_expires_at)
    return {"message": "已退出登录"}


@router.post("/change-password", response_model=TokenResponse, summary="修改自己的密码")
async def change_password(
    payload: PasswordChange,
    response: Response,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM users WHERE id = $1", user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="用户不存在")

    ok = await asyncio.to_thread(verify_password, payload.old_password, row["password_hash"])
    if not ok:
        raise HTTPException(status_code=400, detail="原密码不正确")

    try:
        validate_password_policy(payload.new_password)
        new_hash = await asyncio.to_thread(hash_password, payload.new_password)
    except PasswordPolicyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    updated = await pool.fetchrow(
        """
        UPDATE users
        SET password_hash = $1, token_version = token_version + 1, updated_at = NOW()
        WHERE id = $2
        RETURNING *
        """,
        new_hash,
        user.id,
    )
    # 旧 JWT 全部失效（token_version 已 +1），当前会话用新版本号续签
    if user.jti and user.token_expires_at:
        await blacklist_token(user.jti, user.token_expires_at)
    response.headers["Cache-Control"] = "no-store"
    return _token_payload(updated)


@router.get("/verify", response_model=UserOut, summary="校验当前 token 是否有效")
async def verify(user: CurrentUser = Depends(get_current_user)) -> dict:
    row = await get_pool().fetchrow("SELECT * FROM users WHERE id = $1", user.id)
    if row is None:
        raise HTTPException(status_code=401, detail="账号不存在")
    return user_public(row)


# 保留给未来 OAuth / SSO 的扩展点：
# 可在此模块加入 /auth/oidc/callback、/auth/refresh 等路由，
# 其余业务代码只依赖 deps.CurrentUser，不需要改动。
