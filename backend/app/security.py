"""密码哈希、JWT 签发/校验、API Key 生成。"""
from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from .config import settings

API_KEY_PREFIX = "sk-chat-"


class TokenError(Exception):
    """JWT 无效、过期或类型错误。"""


class PasswordPolicyError(ValueError):
    """密码不满足安全策略。"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_password_policy(password: str) -> None:
    """统一的密码策略：8 位以上、同时包含字母和数字、bcrypt 不超过 72 字节。"""
    if len(password) < 8:
        raise PasswordPolicyError("密码至少需要 8 个字符")
    if len(password.encode("utf-8")) > 72:
        raise PasswordPolicyError("密码过长（bcrypt 上限 72 字节，约 24 个汉字）")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise PasswordPolicyError("密码必须同时包含字母和数字")


def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > 72:
        raise PasswordPolicyError("密码过长（bcrypt 上限 72 字节）")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def hash_api_key(plaintext: str) -> str:
    """API Key 只存 SHA-256 摘要，数据库泄露也无法还原明文。"""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """返回 (明文, 展示前缀, 哈希)。明文只在创建时返回一次。"""
    plaintext = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return plaintext, plaintext[:20], hash_api_key(plaintext)


def is_api_key(token: str) -> bool:
    return token.startswith(API_KEY_PREFIX)


def create_access_token(user_id: int, role: str, token_version: int = 0) -> tuple[str, datetime, str]:
    now = utcnow()
    expires_at = now + timedelta(days=settings.access_token_expire_days)
    jti = uuid.uuid4().hex
    payload = {
        "sub": str(user_id),
        "role": role,
        "ver": int(token_version),
        "type": "access",
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": expires_at,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return token, expires_at, jti


def decode_access_token(token: str) -> dict:
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "jti", "ver"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("无效的登录凭证") from exc

    if payload.get("type") != "access":
        raise TokenError("无效的登录凭证类型")
    try:
        int(payload["sub"])
        int(payload["ver"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TokenError("无效的登录凭证") from exc
    return payload
