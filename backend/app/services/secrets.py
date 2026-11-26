"""用户密钥的对称加密与脱敏。

设计要点：
- 不把模型 API Key 明文写入数据库；
- 用 SECRET_KEY 派生 Fernet 密钥，SECRET_KEY 更换后旧密钥不可恢复，这是有意的安全取舍；
- 日志和 API 响应只返回 hint（末尾 4 位）。
"""
from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings

logger = logging.getLogger(__name__)


def _fernet() -> Fernet:
    digest = hashlib.sha256(f"dreikanterbot:user-secret:{settings.secret_key}".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        logger.warning("用户密钥解密失败：SECRET_KEY 可能已更换")
        return None


def key_hint(plaintext: str) -> str:
    text = (plaintext or "").strip()
    if len(text) <= 4:
        return "…" if text else ""
    return f"…{text[-4:]}"
