"""用户级模型接入配置：BYOK、模型目录、上下文预算。

V3 的硬规则：
1. 聊天必须有一个有效的用户 Key；默认不允许回退到服务端 Key。
2. 上下文不是按“字符数拍脑袋”，而是按模型的 token 窗口计算。
3. 密钥加密后落库，接口只返回 hint。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from ..config import settings
from ..database import get_pool
from .secrets import decrypt_secret, key_hint

logger = logging.getLogger(__name__)

# 官方模型的能力目录。context_window 是该模型允许的最大输入窗口；
# max_output 是单次生成上限。自定义网关可以在设置中覆盖，但受 max_context_window 保护。
MODEL_PRESETS: list[dict] = [
    {
        "id": "deepseek-chat",
        "label": "DeepSeek V3 极速",
        "context_window": 128_000,
        "max_output_tokens": 8_192,
        "reasoning": False,
        "description": "日常问答、写作、代码，响应快，成本低。",
    },
    {
        "id": "deepseek-reasoner",
        "label": "DeepSeek R1 推理",
        "context_window": 128_000,
        "max_output_tokens": 65_536,
        "reasoning": True,
        "description": "复杂分析、数学、代码调试；先展示推理过程。",
    },
    {
        "id": "deepseek-v3.1",
        "label": "DeepSeek V3.1",
        "context_window": 128_000,
        "max_output_tokens": 8_192,
        "reasoning": False,
        "description": "兼容 V3.1 接口的模型名；以你的网关实际能力为准。",
    },
]

PRESET_BY_ID = {item["id"]: item for item in MODEL_PRESETS}
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_REASONER_MODEL = "deepseek-reasoner"


def clamp_context(value: int | None) -> int:
    if not value:
        return settings.default_context_window
    return max(4_096, min(int(value), settings.max_context_window))


def clamp_output(value: int | None, model: str) -> int:
    # 保存时只做全局上限校验；具体模型的上限由 AIConfig.output_for 在调用时收口。
    if not value:
        return settings.deepseek_reasoner_max_tokens
    return max(256, min(int(value), 131_072))


@dataclass
class AIConfig:
    configured: bool
    source: str  # user / server / none
    base_url: str
    api_key: str
    key_hint: str
    model_chat: str
    model_reasoner: str
    context_window: int
    max_output_tokens: int
    temperature: float
    provider: str = "deepseek"
    updated_at: datetime | None = None

    def model_for(self, mode: str) -> str:
        if mode == "reasoner":
            return (self.model_reasoner or self.model_chat or DEFAULT_REASONER_MODEL).strip()
        return (self.model_chat or DEFAULT_MODEL).strip()

    def output_for(self, mode: str) -> int:
        model = self.model_for(mode)
        preset = PRESET_BY_ID.get(model)
        ceiling = int(preset["max_output_tokens"]) if preset else 131_072
        return max(256, min(self.max_output_tokens or ceiling, ceiling))

    def public(self) -> dict:
        return {
            "configured": self.configured,
            "source": self.source,
            "provider": self.provider,
            "base_url": self.base_url,
            "key_hint": self.key_hint,
            "model_chat": self.model_chat,
            "model_reasoner": self.model_reasoner,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "temperature": self.temperature,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "presets": MODEL_PRESETS,
            "max_context_window": settings.max_context_window,
        }


def _server_config() -> AIConfig | None:
    key = (settings.deepseek_api_key or "").strip()
    if key in {"", "sk-please-replace-me"}:
        return None
    return AIConfig(
        configured=True,
        source="server",
        base_url=(settings.deepseek_base_url or "https://api.deepseek.com").rstrip("/"),
        api_key=key,
        key_hint=key_hint(key),
        model_chat=settings.deepseek_model or DEFAULT_MODEL,
        model_reasoner=settings.deepseek_reasoner_model or DEFAULT_REASONER_MODEL,
        context_window=clamp_context(settings.default_context_window),
        max_output_tokens=settings.deepseek_max_tokens,
        temperature=settings.deepseek_temperature,
    )


def _empty_config() -> AIConfig:
    return AIConfig(
        configured=False,
        source="none",
        base_url=(settings.deepseek_base_url or "https://api.deepseek.com").rstrip("/"),
        api_key="",
        key_hint="",
        model_chat=settings.deepseek_model or DEFAULT_MODEL,
        model_reasoner=settings.deepseek_reasoner_model or DEFAULT_REASONER_MODEL,
        context_window=clamp_context(settings.default_context_window),
        max_output_tokens=settings.deepseek_max_tokens,
        temperature=settings.deepseek_temperature,
    )


async def get_ai_config(user_id: int, *, row: dict | None = None) -> AIConfig:
    """读取用户配置；没有用户 Key 时按显式开关决定是否回退服务端 Key。"""
    if row is None:
        row = await get_pool().fetchrow("SELECT * FROM user_ai_settings WHERE user_id = $1", user_id)
    server = _server_config()
    if row:
        api_key = decrypt_secret(row["api_key_encrypted"]) or ""
        if api_key:
            return AIConfig(
                configured=True,
                source="user",
                provider=row["provider"] or "deepseek",
                base_url=(row["base_url"] or settings.deepseek_base_url).rstrip("/"),
                api_key=api_key,
                key_hint=row["key_hint"] or key_hint(api_key),
                model_chat=row["model_chat"] or DEFAULT_MODEL,
                model_reasoner=row["model_reasoner"] or DEFAULT_REASONER_MODEL,
                context_window=clamp_context(row["context_window"]),
                max_output_tokens=int(row["max_output_tokens"] or settings.deepseek_max_tokens),
                temperature=float(row["temperature"] or 1.0),
                updated_at=row["updated_at"],
            )
    if settings.allow_server_key_fallback and server:
        return server
    return _empty_config()


async def save_ai_config(user_id: int, payload: dict) -> AIConfig:
    """保存用户配置。api_key 为空表示保留旧 Key；clear_key=true 表示删除。"""
    from .secrets import encrypt_secret

    pool = get_pool()
    current = await pool.fetchrow("SELECT * FROM user_ai_settings WHERE user_id = $1", user_id)
    model_chat = (payload.get("model_chat") or (current and current["model_chat"]) or DEFAULT_MODEL).strip()
    model_reasoner = (
        payload.get("model_reasoner")
        or (current and current["model_reasoner"])
        or DEFAULT_REASONER_MODEL
    ).strip()
    base_url = (payload.get("base_url") or (current and current["base_url"]) or settings.deepseek_base_url).strip().rstrip("/")
    if not (base_url.startswith("https://") or base_url.startswith("http://")):
        raise ValueError("接口地址必须以 http:// 或 https:// 开头")
    if len(base_url) > 500:
        raise ValueError("接口地址过长")

    clear_key = bool(payload.get("clear_key"))
    raw_key = (payload.get("api_key") or "").strip()
    if raw_key and len(raw_key) < 8:
        raise ValueError("API Key 长度不足，请检查是否复制完整")
    if raw_key and len(raw_key) > 500:
        raise ValueError("API Key 过长")

    encrypted = None if clear_key else (current["api_key_encrypted"] if current else None)
    hint = "" if clear_key else (current["key_hint"] if current else "")
    if raw_key:
        encrypted = encrypt_secret(raw_key)
        hint = key_hint(raw_key)
    elif clear_key:
        encrypted = None
        hint = ""

    context_window = clamp_context(payload.get("context_window") or (current and current["context_window"]))
    max_output = clamp_output(
        payload.get("max_output_tokens") or (current and current["max_output_tokens"]),
        model_chat,
    )
    temperature = float(payload.get("temperature", (current and current["temperature"]) or 1.0))
    temperature = max(0.0, min(temperature, 2.0))

    await pool.execute(
        """
        INSERT INTO user_ai_settings
            (user_id, provider, base_url, api_key_encrypted, key_hint, model_chat,
             model_reasoner, context_window, max_output_tokens, temperature, updated_at)
        VALUES ($1, 'deepseek', $2, $3, $4, $5, $6, $7, $8, $9, NOW())
        ON CONFLICT (user_id) DO UPDATE SET
            base_url = EXCLUDED.base_url,
            api_key_encrypted = EXCLUDED.api_key_encrypted,
            key_hint = EXCLUDED.key_hint,
            model_chat = EXCLUDED.model_chat,
            model_reasoner = EXCLUDED.model_reasoner,
            context_window = EXCLUDED.context_window,
            max_output_tokens = EXCLUDED.max_output_tokens,
            temperature = EXCLUDED.temperature,
            updated_at = NOW()
        """,
        user_id,
        base_url,
        encrypted,
        hint,
        model_chat,
        model_reasoner,
        context_window,
        max_output,
        temperature,
    )
    return await get_ai_config(user_id)
