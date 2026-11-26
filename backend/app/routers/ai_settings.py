"""用户级 AI 接入设置：BYOK、模型、上下文窗口、连接测试。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..deps import CurrentUser, get_current_user
from ..models import AISettingsUpdate
from ..services.ai_config import MODEL_PRESETS, get_ai_config, save_ai_config
from ..services.deepseek import DeepSeekError, test_connection

router = APIRouter(prefix="/settings/ai", tags=["AI 接入"])


@router.get("", summary="读取我的模型接入配置")
async def read_ai_settings(user: CurrentUser = Depends(get_current_user)) -> dict:
    config = await get_ai_config(user.id)
    return config.public()


@router.put("", summary="保存我的模型接入配置（Key 加密落库）")
async def update_ai_settings(
    payload: AISettingsUpdate,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        config = await save_ai_config(user.id, payload.model_dump(exclude_none=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return config.public()


@router.get("/presets", summary="内置模型能力目录")
async def list_presets() -> list[dict]:
    return MODEL_PRESETS


@router.post("/test", summary="验证 Key / 地址 / 模型可用性")
async def test_ai_settings(
    payload: AISettingsUpdate | None = None,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    config = await get_ai_config(user.id)
    if payload and (payload.api_key or payload.base_url or payload.model_chat):
        # 允许在保存前用临时表单测试；Key 只在本次调用内使用，不落库。
        from dataclasses import replace

        data = payload.model_dump(exclude_none=True)
        candidate = replace(
            config,
            api_key=(data.get("api_key") or config.api_key),
            base_url=(data.get("base_url") or config.base_url).rstrip("/"),
            model_chat=(data.get("model_chat") or config.model_chat),
            model_reasoner=(data.get("model_reasoner") or config.model_reasoner),
            context_window=int(data.get("context_window") or config.context_window),
            max_output_tokens=int(data.get("max_output_tokens") or config.max_output_tokens),
            temperature=float(data.get("temperature") or config.temperature),
            configured=True,
            source="user",
        )
        config = candidate
    if not config.api_key:
        raise HTTPException(status_code=400, detail="请先填写 API Key")
    try:
        return await test_connection(config)
    except DeepSeekError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
