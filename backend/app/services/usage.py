"""用量日志：每次 AI 调用都记一条，供管理员统计与后续计费扩展。"""
from __future__ import annotations

import logging

from ..database import get_pool

logger = logging.getLogger(__name__)


async def log_usage(
    user_id: int,
    kind: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    try:
        await get_pool().execute(
            """
            INSERT INTO usage_logs (user_id, kind, tokens_prompt, tokens_completion)
            VALUES ($1, $2, $3, $4)
            """,
            user_id,
            kind,
            max(0, int(prompt_tokens or 0)),
            max(0, int(completion_tokens or 0)),
        )
    except Exception:  # noqa: BLE001 - 统计失败不应影响主流程
        logger.exception("写入 usage_logs 失败 user=%s kind=%s", user_id, kind)
