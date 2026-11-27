"""模型调用：上下文预算、历史裁剪、流式生成、错误翻译。

V3 起模型客户端不再绑死服务端环境变量，而是由调用方传入 AIConfig
（用户自带 Key 或显式开启的服务端兜底）。上下文按 token 预算裁剪，
默认吃满模型的 128K 窗口，而不是旧的固定字符数。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)

from ..config import settings
from .ai_config import AIConfig

logger = logging.getLogger(__name__)

_PLACEHOLDER_KEYS = {"", "sk-please-replace-me"}


class DeepSeekNotConfigured(Exception):
    pass


class DeepSeekError(Exception):
    """带中文用户提示的模型调用错误。"""

    def __init__(self, message: str, *, code: str = "deepseek_error", retryable: bool = False):
        self.message = message
        self.code = code
        self.retryable = retryable
        super().__init__(message)


@dataclass
class StreamEvent:
    content: str = ""
    reasoning: str = ""
    usage: dict | None = None
    finish_reason: str | None = None


@dataclass
class BuiltContext:
    messages: list[dict] = field(default_factory=list)
    trimmed: int = 0
    chars: int = 0
    estimated_tokens: int = 0
    context_window: int = 0
    reserved_output: int = 0


def _server_config() -> AIConfig:
    key = (settings.deepseek_api_key or "").strip()
    return AIConfig(
        configured=key not in _PLACEHOLDER_KEYS,
        source="server" if key not in _PLACEHOLDER_KEYS else "none",
        base_url=(settings.deepseek_base_url or "https://api.deepseek.com").rstrip("/"),
        api_key=key,
        key_hint="",
        model_chat=settings.deepseek_model,
        model_reasoner=settings.deepseek_reasoner_model,
        context_window=settings.default_context_window,
        max_output_tokens=settings.deepseek_max_tokens,
        temperature=settings.deepseek_temperature,
    )


def get_client(
    api_key: str | None = None,
    base_url: str | None = None,
) -> AsyncOpenAI:
    if not api_key:
        server = _server_config()
        api_key = server.api_key
        base_url = base_url or server.base_url
    if not api_key or api_key.strip() in _PLACEHOLDER_KEYS:
        raise DeepSeekNotConfigured("尚未配置模型 API Key，请先在设置 → AI 接入中填写")
    return AsyncOpenAI(
        api_key=api_key,
        base_url=(base_url or "https://api.deepseek.com").rstrip("/"),
        timeout=httpx.Timeout(
            connect=15.0,
            read=float(settings.deepseek_timeout_seconds),
            write=60.0,
            pool=15.0,
        ),
        max_retries=0,  # 流式请求不自动重试，避免重复扣费
    )


def deepseek_configured() -> bool:
    return settings.deepseek_api_key.strip() not in _PLACEHOLDER_KEYS


def _now_text() -> str:
    try:
        tz = ZoneInfo(settings.app_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = timezone.utc
    return datetime.now(tz).strftime("%Y-%m-%d %H:%M（%Z）")


def build_system_prompt() -> str:
    base = (settings.system_prompt or "").strip()
    extra = f"[系统信息] 当前时间：{_now_text()}。请不要声称自己具备实时联网能力，除非工具明确提供。"
    return f"{base}\n\n{extra}" if base else extra


def estimate_tokens(text: str) -> int:
    """保守估算 token：中文/日文/韩文按 0.9 token/字，其他按 0.3 token/字符。

    不追求和某个 tokenizer 完全一致，预算宁可留余量，避免 400 上下文溢出。
    """
    text = text or ""
    cjk = 0
    other = 0
    for char in text:
        code = ord(char)
        if (
            0x4E00 <= code <= 0x9FFF
            or 0x3400 <= code <= 0x4DBF
            or 0x3040 <= code <= 0x30FF
            or 0xAC00 <= code <= 0xD7AF
        ):
            cjk += 1
        else:
            other += 1
    return int(cjk * 0.9 + other * 0.3) + 1


def trim_history(history: Iterable[dict], max_chars: int) -> tuple[list[dict], int]:
    """按字符数裁剪（保留给旧测试/兼容调用）；聊天主路径使用 token 预算。"""
    items = [
        {"role": item["role"], "content": (item.get("content") or "").strip()}
        for item in history
        if item.get("role") in {"user", "assistant"} and (item.get("content") or "").strip()
    ]
    kept: list[dict] = []
    total = 0
    for item in reversed(items):
        size = len(item["content"])
        if kept and total + size > max_chars:
            break
        kept.append(item)
        total += size
    kept.reverse()
    return _merge_adjacent(kept), len(items) - len(kept)


def _merge_adjacent(items: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for item in items:
        if merged and merged[-1]["role"] == item["role"]:
            merged[-1] = {**merged[-1], "content": merged[-1]["content"] + "\n\n" + item["content"]}
        else:
            merged.append(dict(item))
    return merged


def trim_history_tokens(history: Iterable[dict], max_tokens: int) -> tuple[list[dict], int]:
    """从最新消息往回保留，直到 token 预算用完。"""
    items = [
        {"role": item["role"], "content": (item.get("content") or "").strip()}
        for item in history
        if item.get("role") in {"user", "assistant"} and (item.get("content") or "").strip()
    ]
    kept: list[dict] = []
    total = 0
    for item in reversed(items):
        size = estimate_tokens(item["content"])
        if kept and total + size > max_tokens:
            break
        # 单条消息比预算还大时，至少保留当前的用户问题，避免空上下文
        if not kept and size > max_tokens:
            kept.append(item)
            total += size
            break
        kept.append(item)
        total += size
    kept.reverse()
    return _merge_adjacent(kept), len(items) - len(kept)


def model_for_mode(mode: str, config: AIConfig | None = None) -> str:
    config = config or _server_config()
    return config.model_for(mode)


def context_window_for(config: AIConfig | None = None) -> int:
    config = config or _server_config()
    if config.context_window > 0:
        return config.context_window
    return settings.default_context_window


def build_context(
    history: list[dict],
    *,
    mode: str = "chat",
    config: AIConfig | None = None,
) -> BuiltContext:
    config = config or _server_config()
    system_text = build_system_prompt()
    system_tokens = estimate_tokens(system_text)
    window = context_window_for(config)
    output = config.output_for(mode)
    # 给工具/格式/估算误差留 1024 token 余量；至少给历史留 2K。
    budget = max(2_048, window - output - system_tokens - 1_024)
    trimmed, dropped = trim_history_tokens(history, budget)
    messages = [{"role": "system", "content": system_text}, *trimmed]
    chars = sum(len(m["content"]) for m in messages)
    estimated = system_tokens + sum(estimate_tokens(m["content"]) for m in trimmed)
    return BuiltContext(
        messages=messages,
        trimmed=dropped,
        chars=chars,
        estimated_tokens=estimated,
        context_window=window,
        reserved_output=output,
    )


async def test_connection(config: AIConfig, mode: str = "chat") -> dict:
    """最小化真实调用，验证 Key / 地址 / 模型是否可用。"""
    credential = config.credential_for(mode)
    if not credential:
        raise DeepSeekNotConfigured(
            f"{config.provider_for(mode)} 尚未配置 API Key，请先在设置 → AI 接入中填写"
        )
    started = time.monotonic()
    client = get_client(credential["api_key"], credential["base_url"])
    model = config.request_model_for(mode)
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=8,
            temperature=0,
            stream=False,
        )
        latency = int((time.monotonic() - started) * 1000)
        content = ""
        if response.choices:
            content = (response.choices[0].message.content or "").strip()
        return {
            "ok": True,
            "latency_ms": latency,
            "model": model,
            "provider": config.provider_for(mode),
            "message": content[:120] or "连接成功",
        }
    except AuthenticationError as exc:
        raise DeepSeekError("API Key 无效或已失效", code="auth_error") from exc
    except RateLimitError as exc:
        raise DeepSeekError("上游限流，请稍后再试", code="upstream_rate_limit") from exc
    except (APITimeoutError, APIConnectionError) as exc:
        raise DeepSeekError("连接失败：地址不可达或超时", code="upstream_unreachable") from exc
    except APIError as exc:
        status = getattr(exc, "status_code", None)
        raise DeepSeekError(f"接口返回错误（HTTP {status or 'unknown'}）", code="upstream_error") from exc
    except DeepSeekError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("测试模型连接失败")
        raise DeepSeekError("无法连接模型服务，请检查地址和 Key", code="internal_error") from exc


async def stream_completion(
    history: list[dict],
    *,
    mode: str = "chat",
    config: AIConfig | None = None,
) -> AsyncIterator[StreamEvent]:
    """把历史交给模型，逐块 yield。config 必须由调用方提供（用户 Key）。"""
    config = config or _server_config()
    credential = config.credential_for(mode)
    if not credential:
        raise DeepSeekNotConfigured(
            f"{config.provider_for(mode)} 尚未配置 API Key，请先在设置 → AI 接入中填写"
        )
    client = get_client(credential["api_key"], credential["base_url"])
    model = config.request_model_for(mode)
    context = build_context(history, mode=mode, config=config)
    max_tokens = config.output_for(mode)
    logger.info(
        "调用模型 source=%s provider=%s mode=%s model=%s messages=%s estimated_tokens=%s window=%s output=%s trimmed=%s",
        config.source,
        config.provider_for(mode),
        mode,
        model,
        len(context.messages),
        context.estimated_tokens,
        context.context_window,
        max_tokens,
        context.trimmed,
    )
    try:
        kwargs = {
            "model": model,
            "messages": context.messages,
            "stream": True,
            "max_tokens": max_tokens,
        }
        if config.provider_for(mode) != "local":
            kwargs["stream_options"] = {"include_usage": True}
        if mode == "chat":
            kwargs["temperature"] = config.temperature
        effort = config.effort_for(mode)
        if effort:
            kwargs["extra_body"] = {"reasoning_effort": effort}
        stream = await client.chat.completions.create(**kwargs)
        usage: dict | None = None
        finish_reason: str | None = None
        try:
            async for chunk in stream:
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:
                    details = getattr(chunk_usage, "completion_tokens_details", None)
                    usage = {
                        "prompt_tokens": int(getattr(chunk_usage, "prompt_tokens", 0) or 0),
                        "completion_tokens": int(getattr(chunk_usage, "completion_tokens", 0) or 0),
                        "total_tokens": int(getattr(chunk_usage, "total_tokens", 0) or 0),
                        "reasoning_tokens": int(getattr(details, "reasoning_tokens", 0) or 0),
                    }
                if not getattr(chunk, "choices", None):
                    continue
                choice = chunk.choices[0]
                if getattr(choice, "finish_reason", None):
                    finish_reason = choice.finish_reason
                delta = getattr(choice, "delta", None)
                reasoning = None
                if delta:
                    reasoning = getattr(delta, "reasoning_content", None) or getattr(
                        delta, "reasoning", None
                    )
                if reasoning:
                    yield StreamEvent(reasoning=reasoning)
                content = getattr(delta, "content", None) if delta else None
                if content:
                    yield StreamEvent(content=content)
            yield StreamEvent(usage=usage, finish_reason=finish_reason)
        finally:
            try:
                await stream.close()
            except Exception:  # noqa: BLE001
                pass
    except AuthenticationError as exc:
        logger.error("模型鉴权失败：%s", exc)
        raise DeepSeekError("API Key 无效或已失效，请在设置 → AI 接入中更新", code="auth_error") from exc
    except RateLimitError as exc:
        logger.warning("模型上游限流：%s", exc)
        raise DeepSeekError("上游限流，请稍后再试", code="upstream_rate_limit", retryable=True) from exc
    except (APITimeoutError, APIConnectionError) as exc:
        logger.warning("模型连接失败：%s", exc)
        raise DeepSeekError("连接模型服务超时或网络异常，请稍后重试", code="upstream_unreachable", retryable=True) from exc
    except APIError as exc:
        status = getattr(exc, "status_code", None)
        logger.error("模型 API 错误 status=%s err=%s", status, exc)
        raise DeepSeekError(f"模型接口返回错误（HTTP {status or 'unknown'}）", code="upstream_error", retryable=True) from exc
    except DeepSeekError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("模型调用出现未预期异常")
        raise DeepSeekError("模型服务暂时不可用，请稍后重试", code="internal_error") from exc
