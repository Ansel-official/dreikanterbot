"""用户级多 Provider 模型接入：DeepSeek + 月之暗面 Kimi。

V3.1 起一个账号可以同时保存两个 Provider 的 Key：
- DeepSeek：deepseek-flash / deepseek-v4-pro / deepseek-chat / deepseek-reasoner
- Moonshot：kimi-k2.6 / kimi-k2.7-code / kimi-k2.7-code-highspeed / kimi-k3 / kimi-k3.1

模型决定 Provider，Provider 决定 base_url 与 Key。上下文按 token 预算裁剪，
API Key 加密落库，接口只返回 hint。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime

from ..config import settings
from ..database import get_pool
from .secrets import decrypt_secret, encrypt_secret, key_hint

logger = logging.getLogger(__name__)

PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "id": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "key_placeholder": "sk-...",
        "description": "DeepSeek 官方 API；V4.1 Flash / V4 Pro / V3.1 别名。",
    },
    "moonshot": {
        "id": "moonshot",
        "label": "月之暗面 Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "key_placeholder": "sk-...",
        "description": "Moonshot 官方 API；Kimi K2.6 / K2.7 Code / K3。",
    },
    "local": {
        "id": "local",
        "label": "本地模型",
        "base_url": "http://127.0.0.1:11434/v1",
        "key_placeholder": "无需 Key",
        "description": "Ollama / LM Studio / vLLM 等 OpenAI 兼容本地服务。",
        "requires_key": False,
    },
}

# 官方模型元数据来自 DeepSeek / Moonshot 的模型目录。
# 输出上限为服务端 max_tokens 上限；UI 仍允许用户调低。
MODEL_PRESETS: list[dict] = [
    {
        "id": "deepseek-flash",
        "label": "DeepSeek V4.1 Flash",
        "provider": "deepseek",
        "context_window": 1_048_576,
        "max_output_tokens": 393_216,
        "reasoning": True,
        "description": "DeepSeek 当前主力模型：1M 上下文、384K 输出，支持思考与多模态输入。",
    },
    {
        "id": "deepseek-v4-pro",
        "label": "DeepSeek V4 Pro",
        "provider": "deepseek",
        "context_window": 1_048_576,
        "max_output_tokens": 393_216,
        "reasoning": True,
        "description": "DeepSeek V4 Pro（0813）：1M 上下文、384K 输出，适合复杂任务。",
    },
    {
        "id": "deepseek-v4-flash",
        "label": "DeepSeek V4 Flash（旧名）",
        "provider": "deepseek",
        "context_window": 1_048_576,
        "max_output_tokens": 393_216,
        "reasoning": True,
        "description": "旧模型名；官方仍可调用，实际由 DeepSeek-V4.1-Flash 提供服务。",
    },
    {
        "id": "deepseek-v4-flash-vision-exp",
        "label": "DeepSeek V4 Flash Vision（旧名）",
        "provider": "deepseek",
        "context_window": 1_048_576,
        "max_output_tokens": 393_216,
        "reasoning": True,
        "description": "旧视觉实验模型名；官方仍可调用，实际由 V4.1 Flash 提供服务。",
    },
    {
        "id": "deepseek-chat",
        "label": "DeepSeek V3.1 Chat",
        "provider": "deepseek",
        "context_window": 131_072,
        "max_output_tokens": 8_192,
        "reasoning": False,
        "description": "DeepSeek V3.1 非思考模式别名，128K 上下文。",
    },
    {
        "id": "deepseek-reasoner",
        "label": "DeepSeek V3.1 Reasoner",
        "provider": "deepseek",
        "context_window": 131_072,
        "max_output_tokens": 65_536,
        "reasoning": True,
        "description": "DeepSeek V3.1 思考模式别名，128K 上下文、64K 输出。",
    },
    {
        "id": "kimi-k2.6",
        "label": "Kimi K2.6",
        "provider": "moonshot",
        "context_window": 262_144,
        "max_output_tokens": 262_144,
        "reasoning": True,
        "description": "Kimi K2.6，256K 上下文；适合通用对话与代码。",
    },
    {
        "id": "kimi-k2.7-code",
        "label": "Kimi K2.7 Code",
        "provider": "moonshot",
        "context_window": 262_144,
        "max_output_tokens": 262_144,
        "reasoning": True,
        "description": "Kimi K2.7 Code，面向代码与长任务。",
    },
    {
        "id": "kimi-k2.7-code-highspeed",
        "label": "Kimi K2.7 Code HighSpeed",
        "provider": "moonshot",
        "context_window": 262_144,
        "max_output_tokens": 262_144,
        "reasoning": True,
        "description": "Kimi K2.7 Code 高速版，低延迟代码任务。",
    },
    {
        "id": "kimi-k3",
        "label": "Kimi K3",
        "provider": "moonshot",
        "context_window": 1_048_576,
        "max_output_tokens": 1_048_576,
        "reasoning": True,
        "description": "Kimi K3，1M 上下文，适合超长材料。",
    },
    {
        "id": "kimi-k3.1-pro",
        "label": "Kimi K3.1 Pro",
        "provider": "moonshot",
        "context_window": 1_000_000,
        "max_output_tokens": 128_000,
        "reasoning": True,
        "description": "Kimi K3.1 Pro，1M 上下文、128K 输出；Moonshot 当前模型。",
    },
    {
        "id": "local/deepseek-r1:8b-6g",
        "label": "DeepSeek R1 8B（本地 6G）",
        "provider": "local",
        "context_window": 32_768,
        "max_output_tokens": 8_192,
        "reasoning": True,
        "description": "本机 Ollama 模型，显存优化版；实际能力取决于本机配置。",
    },
    {
        "id": "local/deepseek-r1:8b",
        "label": "DeepSeek R1 8B（本地）",
        "provider": "local",
        "context_window": 32_768,
        "max_output_tokens": 8_192,
        "reasoning": True,
        "description": "本机 Ollama 模型；实际能力取决于本机配置。",
    },
]

EFFORT_LEVELS = ("low", "high", "max")
DEFAULT_EFFORT = "high"
_EFFORT_MODELS = {
    "deepseek-flash",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "deepseek-v4-flash-vision-exp",
    "kimi-k2.6",
    "kimi-k2.7-code",
    "kimi-k2.7-code-highspeed",
    "kimi-k3",
    "kimi-k3.1-pro",
}
for _item in MODEL_PRESETS:
    _item["efforts"] = list(EFFORT_LEVELS) if _item["id"] in _EFFORT_MODELS else []

PRESET_BY_ID = {item["id"]: item for item in MODEL_PRESETS}
DEFAULT_MODEL = "deepseek-flash"
DEFAULT_REASONER_MODEL = "deepseek-v4-pro"
VALID_PROVIDERS = set(PROVIDERS)


def clamp_context(value: int | None) -> int:
    if not value:
        return settings.default_context_window
    return max(4_096, min(int(value), settings.max_context_window))


def clamp_output(value: int | None, model: str = "") -> int:
    if not value:
        return settings.deepseek_reasoner_max_tokens
    return max(256, min(int(value), 1_048_576))


def provider_for_model(model: str) -> str:
    model = (model or "").strip()
    if model.startswith("local/"):
        return "local"
    preset = PRESET_BY_ID.get(model)
    if preset:
        return preset["provider"]
    if model.lower().startswith("kimi"):
        return "moonshot"
    return "deepseek"


def provider_requires_key(provider: str) -> bool:
    return bool(PROVIDERS.get(provider, {}).get("requires_key", True))


def provider_base_url(provider: str) -> str:
    return (PROVIDERS.get(provider, PROVIDERS["deepseek"]).get("base_url") or "").rstrip("/")


def provider_public() -> list[dict]:
    return [
        {
            **meta,
            "models": [item["id"] for item in MODEL_PRESETS if item["provider"] == provider],
        }
        for provider, meta in PROVIDERS.items()
    ]


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
    reasoning_effort: str = DEFAULT_EFFORT
    provider: str = "deepseek"
    provider_keys: dict[str, dict] = field(default_factory=dict)
    updated_at: datetime | None = None

    def model_for(self, mode: str) -> str:
        if mode == "reasoner":
            return (self.model_reasoner or self.model_chat or DEFAULT_REASONER_MODEL).strip()
        return (self.model_chat or DEFAULT_MODEL).strip()

    def provider_for(self, mode: str) -> str:
        return provider_for_model(self.model_for(mode))

    def request_model_for(self, mode: str) -> str:
        model = self.model_for(mode)
        if model.startswith("local/"):
            return model[len("local/") :]
        return model

    def efforts_for(self, mode: str) -> list[str]:
        preset = PRESET_BY_ID.get(self.model_for(mode))
        return list(preset.get("efforts", [])) if preset else []

    def effort_for(self, mode: str) -> str:
        """只有模型声明支持 effort 时才发送，避免本地/旧模型报错。"""
        efforts = self.efforts_for(mode)
        if self.reasoning_effort in efforts:
            return self.reasoning_effort
        return ""

    def credential_for(self, mode: str) -> dict | None:
        provider = self.provider_for(mode)
        data = (self.provider_keys or {}).get(provider) or {}
        if provider == "local":
            return {
                "api_key": data.get("api_key") or "ollama",
                "base_url": (data.get("base_url") or provider_base_url("local")).rstrip("/"),
            }
        if data.get("api_key"):
            return {
                "api_key": data["api_key"],
                "base_url": (data.get("base_url") or provider_base_url(provider)).rstrip("/"),
            }
        if provider == self.provider and self.api_key:
            return {
                "api_key": self.api_key,
                "base_url": (self.base_url or provider_base_url(provider)).rstrip("/"),
            }
        return None

    def ready_for(self, mode: str) -> bool:
        return self.credential_for(mode) is not None

    def output_for(self, mode: str) -> int:
        model = self.model_for(mode)
        preset = PRESET_BY_ID.get(model)
        if preset:
            ceiling = int(preset["max_output_tokens"])
        elif provider_for_model(model) == "local":
            ceiling = 8_192
        else:
            ceiling = 393_216
        return max(256, min(self.max_output_tokens or ceiling, ceiling))

    def public(self) -> dict:
        status = {}
        for provider, meta in PROVIDERS.items():
            data = (self.provider_keys or {}).get(provider) or {}
            key = data.get("api_key") or (self.api_key if provider == self.provider else "")
            is_local = provider == "local"
            status[provider] = {
                "configured": bool(key) or is_local,
                "hint": "本地" if is_local else data.get("hint") or (
                    self.key_hint if provider == self.provider else ""
                ),
                "base_url": data.get("base_url") or (
                    self.base_url if provider == self.provider else meta["base_url"]
                ),
                "requires_key": provider_requires_key(provider),
            }
        chat = self.credential_for("chat")
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
            "reasoning_effort": self.reasoning_effort,
            "efforts_for_chat": self.efforts_for("chat"),
            "efforts_for_reasoner": self.efforts_for("reasoner"),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "presets": MODEL_PRESETS,
            "providers": provider_public(),
            "provider_status": status,
            "chat_ready": chat is not None,
            "reasoner_ready": self.credential_for("reasoner") is not None,
            "max_context_window": settings.max_context_window,
        }


def _server_credentials() -> dict[str, dict]:
    creds: dict[str, dict] = {}
    deepseek_key = (settings.deepseek_api_key or "").strip()
    if deepseek_key and deepseek_key != "sk-please-replace-me":
        creds["deepseek"] = {
            "api_key": deepseek_key,
            "base_url": (settings.deepseek_base_url or provider_base_url("deepseek")).rstrip("/"),
            "hint": key_hint(deepseek_key),
        }
    moonshot_key = (settings.moonshot_api_key or "").strip()
    if moonshot_key:
        creds["moonshot"] = {
            "api_key": moonshot_key,
            "base_url": (settings.moonshot_base_url or provider_base_url("moonshot")).rstrip("/"),
            "hint": key_hint(moonshot_key),
        }
    return creds


def _empty_config() -> AIConfig:
    return AIConfig(
        configured=False,
        source="none",
        base_url=provider_base_url("deepseek"),
        api_key="",
        key_hint="",
        model_chat=settings.deepseek_model or DEFAULT_MODEL,
        model_reasoner=settings.deepseek_reasoner_model or DEFAULT_REASONER_MODEL,
        context_window=clamp_context(settings.default_context_window),
        max_output_tokens=settings.deepseek_max_tokens,
        temperature=settings.deepseek_temperature,
    )


def _decode_provider_keys(raw: object) -> dict[str, dict]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (TypeError, ValueError):
            raw = {}
    if not isinstance(raw, dict):
        return {}
    decoded: dict[str, dict] = {}
    for provider, data in raw.items():
        if provider not in VALID_PROVIDERS or not isinstance(data, dict):
            continue
        if provider == "local":
            decoded[provider] = {
                "api_key": "ollama",
                "base_url": (data.get("base_url") or provider_base_url("local")).rstrip("/"),
                "hint": "本地",
            }
            continue
        key = decrypt_secret(data.get("encrypted"))
        if not key:
            continue
        decoded[provider] = {
            "api_key": key,
            "base_url": (data.get("base_url") or provider_base_url(provider)).rstrip("/"),
            "hint": data.get("hint") or key_hint(key),
        }
    return decoded


async def get_ai_config(user_id: int, *, row: dict | None = None) -> AIConfig:
    if row is None:
        row = await get_pool().fetchrow("SELECT * FROM user_ai_settings WHERE user_id = $1", user_id)
    provider_keys = _decode_provider_keys(row["provider_keys"] if row else {})
    source = "user" if provider_keys else "none"

    model_chat = (row["model_chat"] if row else settings.deepseek_model) or DEFAULT_MODEL
    model_reasoner = (
        (row["model_reasoner"] if row else settings.deepseek_reasoner_model) or DEFAULT_REASONER_MODEL
    )
    provider = (row["provider"] if row else None) or provider_for_model(model_chat)
    base_url = (row["base_url"] if row else provider_base_url(provider)) or provider_base_url(provider)

    if row and row["api_key_encrypted"]:
        legacy = decrypt_secret(row["api_key_encrypted"])
        if legacy and provider not in provider_keys:
            provider_keys[provider] = {
                "api_key": legacy,
                "base_url": (row["base_url"] or provider_base_url(provider)).rstrip("/"),
                "hint": row["key_hint"] or key_hint(legacy),
            }
            source = "user"

    if not provider_keys and settings.allow_server_key_fallback:
        provider_keys = _server_credentials()
        source = "server" if provider_keys else "none"

    context_window = clamp_context(
        (row["context_window"] if row else settings.default_context_window)
    )
    max_output = int((row["max_output_tokens"] if row else settings.deepseek_max_tokens) or 0)
    temperature = float((row["temperature"] if row else settings.deepseek_temperature) or 1.0)
    reasoning_effort = (row["reasoning_effort"] if row else DEFAULT_EFFORT) or DEFAULT_EFFORT
    if reasoning_effort not in EFFORT_LEVELS:
        reasoning_effort = DEFAULT_EFFORT
    provider = provider_for_model(model_chat)
    if provider == "local":
        context_window = min(context_window, 32_768)
        max_output = min(max_output, 8_192)
    chat_cred = provider_keys.get(provider) or {}
    config = AIConfig(
        configured=False,
        source=source,
        provider=provider,
        base_url=(chat_cred.get("base_url") or base_url or provider_base_url(provider)).rstrip("/"),
        api_key=chat_cred.get("api_key", ""),
        key_hint=chat_cred.get("hint", "") or (row["key_hint"] if row else ""),
        model_chat=model_chat,
        model_reasoner=model_reasoner,
        context_window=context_window,
        max_output_tokens=max(max_output, 256),
        temperature=temperature,
        reasoning_effort=reasoning_effort,
        provider_keys=provider_keys,
        updated_at=row["updated_at"] if row else None,
    )
    config.configured = bool(config.ready_for("chat") or config.ready_for("reasoner"))
    return config


def _normalise_provider_updates(payload: dict) -> dict[str, dict]:
    updates: dict[str, dict] = {}
    raw = payload.get("provider_keys")
    if isinstance(raw, dict):
        for provider, item in raw.items():
            if provider not in VALID_PROVIDERS:
                raise ValueError(f"不支持的 Provider：{provider}")
            if hasattr(item, "model_dump"):
                item = item.model_dump(exclude_none=True)
            if isinstance(item, dict):
                updates[provider] = item
    target = payload.get("provider") or "deepseek"
    if target not in VALID_PROVIDERS:
        raise ValueError(f"不支持的 Provider：{target}")
    if payload.get("api_key"):
        updates.setdefault(target, {})["api_key"] = payload["api_key"]
        if payload.get("base_url"):
            updates[target]["base_url"] = payload["base_url"]
    return updates


async def save_ai_config(user_id: int, payload: dict) -> AIConfig:
    pool = get_pool()
    current = await pool.fetchrow("SELECT * FROM user_ai_settings WHERE user_id = $1", user_id)
    raw_keys = current["provider_keys"] if current and isinstance(current["provider_keys"], dict) else {}
    enc_keys: dict[str, dict] = {}
    for provider, item in raw_keys.items():
        if provider in VALID_PROVIDERS and isinstance(item, dict):
            enc_keys[provider] = {
                "encrypted": item.get("encrypted"),
                "hint": item.get("hint") or "",
                "base_url": item.get("base_url") or provider_base_url(provider),
            }

    updates = _normalise_provider_updates(payload)
    target = payload.get("provider") or provider_for_model(
        payload.get("model_chat") or (current["model_chat"] if current else DEFAULT_MODEL)
    )
    if target not in VALID_PROVIDERS:
        target = "deepseek"
    if payload.get("clear_key") and not updates:
        updates[target] = {"clear_key": True}

    for provider, item in updates.items():
        existing = enc_keys.get(provider, {})
        base_url = (item.get("base_url") or existing.get("base_url") or provider_base_url(provider)).strip().rstrip("/")
        if not (base_url.startswith("https://") or base_url.startswith("http://")):
            raise ValueError("接口地址必须以 http:// 或 https:// 开头")
        if len(base_url) > 500:
            raise ValueError("接口地址过长")
        encrypted = existing.get("encrypted")
        hint = existing.get("hint") or ""
        if item.get("clear_key"):
            encrypted = None
            hint = ""
        raw_key = (item.get("api_key") or "").strip()
        if raw_key:
            if len(raw_key) < 8:
                raise ValueError(f"{PROVIDERS[provider]['label']} 的 API Key 长度不足")
            if len(raw_key) > 500:
                raise ValueError("API Key 过长")
            encrypted = encrypt_secret(raw_key)
            hint = key_hint(raw_key)
        enc_keys[provider] = {"encrypted": encrypted, "hint": hint, "base_url": base_url}

    model_chat = (payload.get("model_chat") or (current["model_chat"] if current else DEFAULT_MODEL)).strip()
    model_reasoner = (
        payload.get("model_reasoner")
        or (current["model_reasoner"] if current else DEFAULT_REASONER_MODEL)
    ).strip()
    target = provider_for_model(model_chat)
    context_window = clamp_context(
        payload.get("context_window")
        or (current["context_window"] if current else settings.default_context_window)
    )
    max_output = clamp_output(
        payload.get("max_output_tokens")
        or (current["max_output_tokens"] if current else settings.deepseek_max_tokens),
        model_chat,
    )
    if target == "local":
        context_window = min(context_window, 32_768)
        max_output = min(max_output, 8_192)
    temperature = float(
        payload.get("temperature", (current["temperature"] if current else settings.deepseek_temperature) or 1.0)
    )
    temperature = max(0.0, min(temperature, 2.0))
    reasoning_effort = (
        payload.get("reasoning_effort")
        or (current["reasoning_effort"] if current else DEFAULT_EFFORT)
        or DEFAULT_EFFORT
    )
    if reasoning_effort not in EFFORT_LEVELS:
        reasoning_effort = DEFAULT_EFFORT

    # 兼容旧列：始终写当前聊天模型所在的 Provider。
    legacy = enc_keys.get(target, {})
    legacy_encrypted = legacy.get("encrypted")
    legacy_hint = legacy.get("hint") or ""
    legacy_base = legacy.get("base_url") or provider_base_url(target)

    await pool.execute(
        """
        INSERT INTO user_ai_settings
            (user_id, provider, base_url, api_key_encrypted, key_hint, model_chat,
             model_reasoner, context_window, max_output_tokens, temperature, reasoning_effort,
             provider_keys, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
        ON CONFLICT (user_id) DO UPDATE SET
            provider = EXCLUDED.provider,
            base_url = EXCLUDED.base_url,
            api_key_encrypted = EXCLUDED.api_key_encrypted,
            key_hint = EXCLUDED.key_hint,
            model_chat = EXCLUDED.model_chat,
            model_reasoner = EXCLUDED.model_reasoner,
            context_window = EXCLUDED.context_window,
            max_output_tokens = EXCLUDED.max_output_tokens,
            temperature = EXCLUDED.temperature,
            reasoning_effort = EXCLUDED.reasoning_effort,
            provider_keys = EXCLUDED.provider_keys,
            updated_at = NOW()
        """,
        user_id,
        target,
        legacy_base,
        legacy_encrypted,
        legacy_hint,
        model_chat,
        model_reasoner,
        context_window,
        max_output,
        temperature,
        reasoning_effort,
        enc_keys,
    )
    return await get_ai_config(user_id)


def preview_ai_config(config: AIConfig, payload: dict) -> AIConfig:
    """用于连接测试：把表单值合到当前配置上，但不落库。"""
    provider_keys = {key: dict(value) for key, value in (config.provider_keys or {}).items()}
    updates = _normalise_provider_updates(payload)
    for provider, item in updates.items():
        current = provider_keys.get(provider, {})
        if item.get("clear_key"):
            provider_keys.pop(provider, None)
            continue
        key = (item.get("api_key") or current.get("api_key") or "").strip()
        if provider == "local":
            provider_keys[provider] = {
                "api_key": "ollama",
                "base_url": (item.get("base_url") or current.get("base_url") or provider_base_url(provider)).rstrip("/"),
                "hint": "本地",
            }
        elif key:
            provider_keys[provider] = {
                "api_key": key,
                "base_url": (item.get("base_url") or current.get("base_url") or provider_base_url(provider)).rstrip("/"),
                "hint": key_hint(key),
            }
    model_chat = payload.get("model_chat") or config.model_chat
    model_reasoner = payload.get("model_reasoner") or config.model_reasoner
    context_window = clamp_context(payload.get("context_window") or config.context_window)
    max_output = clamp_output(
        payload.get("max_output_tokens") or config.max_output_tokens, model_chat
    )
    if provider_for_model(model_chat) == "local":
        context_window = min(context_window, 32_768)
        max_output = min(max_output, 8_192)
    effort = payload.get("reasoning_effort") or config.reasoning_effort
    if effort not in EFFORT_LEVELS:
        effort = DEFAULT_EFFORT
    candidate = replace(
        config,
        provider_keys=provider_keys,
        model_chat=model_chat,
        model_reasoner=model_reasoner,
        context_window=context_window,
        max_output_tokens=max_output,
        temperature=float(payload.get("temperature") or config.temperature),
        reasoning_effort=effort,
        provider=provider_for_model(model_chat),
    )
    candidate.configured = bool(candidate.ready_for("chat") or candidate.ready_for("reasoner"))
    return candidate
