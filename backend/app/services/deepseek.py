"""DeepSeek 官方 API 封装：历史拼接、上下文裁剪、流式生成、错误翻译。"""
from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None
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


def get_client() -> AsyncOpenAI:
    global _client
    if settings.deepseek_api_key.strip() in _PLACEHOLDER_KEYS:
        raise DeepSeekNotConfigured("服务端未配置 DEEPSEEK_API_KEY")
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url.rstrip("/"),
            timeout=httpx.Timeout(
                connect=10.0,
                read=float(settings.deepseek_timeout_seconds),
                write=30.0,
                pool=10.0,
            ),
            max_retries=0,  # 流式请求不做自动重试，避免重复扣费；由用户手动重试
        )
    return _client


def deepseek_configured() -> bool:
    return settings.deepseek_api_key.strip() not in _PLACEHOLDER_KEYS


def _now_text() -> str:
    try:
        tz = ZoneInfo(settings.app_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = timezone.utc
    now = datetime.now(tz)
    return now.strftime("%Y-%m-%d %H:%M（%Z）")


def build_system_prompt() -> str:
    base = (settings.system_prompt or "").strip()
    extra = f"[系统信息] 当前时间：{_now_text()}。请不要声称自己具备实时联网能力，除非工具明确提供。"
    return f"{base}\n\n{extra}" if base else extra


def trim_history(history: Iterable[dict], max_chars: int) -> tuple[list[dict], int]:
    """从最新往回保留消息，按字符数裁剪，返回 (裁剪后消息, 丢弃条数)。"""
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

    # 合并相邻同角色消息，兼容部分网关对角色交替的严格要求
    merged: list[dict] = []
    for item in kept:
        if merged and merged[-1]["role"] == item["role"]:
            merged[-1]["content"] += "\n\n" + item["content"]
        else:
            merged.append(dict(item))
    return merged, len(items) - len(kept)


def model_for_mode(mode: str) -> str:
    if mode == "reasoner":
        return (settings.deepseek_reasoner_model or settings.deepseek_model).strip()
    return settings.deepseek_model


def context_chars_for_mode(mode: str) -> int:
    if mode == "reasoner":
        return settings.deepseek_reasoner_context_chars
    return settings.deepseek_context_chars


def build_context(history: list[dict], *, mode: str = "chat") -> BuiltContext:
    trimmed, dropped = trim_history(history, context_chars_for_mode(mode))
    system = {"role": "system", "content": build_system_prompt()}
    messages = [system, *trimmed]
    chars = sum(len(m["content"]) for m in messages)
    return BuiltContext(messages=messages, trimmed=dropped, chars=chars)


async def stream_completion(
    history: list[dict], *, mode: str = "chat"
) -> AsyncIterator[StreamEvent]:
    """把完整历史交给 DeepSeek，逐块 yield 文本；最后一块携带 usage。"""
    client = get_client()
    model = model_for_mode(mode)
    context = build_context(history, mode=mode)
    max_tokens = (
        settings.deepseek_reasoner_max_tokens if mode == "reasoner" else settings.deepseek_max_tokens
    )
    logger.info(
        "调用 DeepSeek mode=%s model=%s messages=%s chars=%s trimmed=%s",
        mode,
        model,
        len(context.messages),
        context.chars,
        context.trimmed,
    )
    try:
        kwargs = {
            "model": model,
            "messages": context.messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": max_tokens,
        }
        # deepseek-reasoner 不支持 temperature / top_p 等采样参数
        if mode == "chat":
            kwargs["temperature"] = settings.deepseek_temperature
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
                reasoning = getattr(delta, "reasoning_content", None) if delta else None
                if reasoning:
                    yield StreamEvent(reasoning=reasoning)
                content = getattr(delta, "content", None) if delta else None
                if content:
                    yield StreamEvent(content=content)
            yield StreamEvent(usage=usage, finish_reason=finish_reason)
        finally:
            # 用户点击停止或连接断开时，及时关闭上游 HTTP 流，避免连接泄漏
            try:
                await stream.close()
            except Exception:  # noqa: BLE001
                pass
    except AuthenticationError as exc:
        logger.error("DeepSeek 鉴权失败：%s", exc)
        raise DeepSeekError("DeepSeek API Key 无效或已失效，请联系管理员检查配置", code="auth_error") from exc
    except RateLimitError as exc:
        logger.warning("DeepSeek 上游限流：%s", exc)
        raise DeepSeekError("DeepSeek 上游限流，请稍后再试", code="upstream_rate_limit", retryable=True) from exc
    except (APITimeoutError, APIConnectionError) as exc:
        logger.warning("DeepSeek 连接失败：%s", exc)
        raise DeepSeekError("连接 DeepSeek 超时或网络异常，请稍后重试", code="upstream_unreachable", retryable=True) from exc
    except APIError as exc:
        status = getattr(exc, "status_code", None)
        logger.error("DeepSeek API 错误 status=%s err=%s", status, exc)
        raise DeepSeekError(f"DeepSeek 接口返回错误（HTTP {status or 'unknown'}）", code="upstream_error", retryable=True) from exc
    except DeepSeekError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("DeepSeek 调用出现未预期异常")
        raise DeepSeekError("AI 服务暂时不可用，请稍后重试", code="internal_error") from exc
