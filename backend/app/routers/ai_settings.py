"""用户级 AI 接入设置：BYOK、模型、上下文窗口、连接测试。"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import CurrentUser, get_current_user
from ..models import AISettingsUpdate
from ..services.ai_config import (
    MODEL_PRESETS,
    PROVIDERS,
    get_ai_config,
    preview_ai_config,
    provider_public,
    save_ai_config,
)
from ..services.deepseek import DeepSeekError, DeepSeekNotConfigured, test_connection

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


@router.get("/presets", summary="内置模型能力目录（DeepSeek + Kimi）")
async def list_presets() -> dict:
    return {"providers": provider_public(), "models": MODEL_PRESETS}


def _normalise_local_base(value: str | None) -> str:
    base = (value or PROVIDERS["local"]["base_url"]).strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="本地模型地址必须使用 http:// 或 https://")
    if len(base) > 500:
        raise HTTPException(status_code=422, detail="本地模型地址过长")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return base


@router.get("/local/models", summary="检测 Ollama / OpenAI 兼容本地模型")
async def list_local_models(
    base_url: str | None = Query(default=None, max_length=500),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    base = _normalise_local_base(base_url)
    root = base[:-3].rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            names: list[str] = []
            source = "openai"
            try:
                response = await client.get(
                    f"{base}/models",
                    headers={"Authorization": "Bearer ollama"},
                )
                if response.status_code == 200:
                    names = [
                        str(item.get("id")).strip()
                        for item in response.json().get("data", [])
                        if item.get("id")
                    ]
                else:
                    source = "ollama"
            except httpx.HTTPError:
                source = "ollama"
            if not names:
                response = await client.get(f"{root}/api/tags")
                response.raise_for_status()
                names = [
                    str(item.get("name")).strip()
                    for item in response.json().get("models", [])
                    if item.get("name")
                ]
                source = "ollama"
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="连不上本地模型服务；请确认 Ollama 已启动，地址类似 http://127.0.0.1:11434",
        ) from exc
    models = []
    seen = set()
    for name in names:
        name = name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        lowered = name.lower()
        models.append(
            {
                "id": f"local/{name}",
                "label": f"{name}（本地）",
                "provider": "local",
                "context_window": 32_768,
                "max_output_tokens": 8_192,
                "reasoning": "r1" in lowered or "reason" in lowered,
                "description": "本机 Ollama 模型；实际上下文与显存占用取决于本机配置。",
            }
        )
    if not models:
        raise HTTPException(status_code=400, detail="本地服务没有返回模型，请先 ollama pull 一个模型")
    return {"base_url": base, "source": source, "models": models}


@router.post("/test", summary="验证 Key / 地址 / 模型可用性")
async def test_ai_settings(
    payload: AISettingsUpdate | None = None,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    config = await get_ai_config(user.id)
    if payload:
        # 允许在保存前用临时表单测试；Key 只在本次调用内使用，不落库。
        config = preview_ai_config(config, payload.model_dump(exclude_none=True))
    try:
        return await test_connection(config, mode="chat")
    except DeepSeekNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DeepSeekError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc
