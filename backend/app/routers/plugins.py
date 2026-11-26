"""声明式插件中心：上传 ZIP 安装、启停、删除。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from ..deps import CurrentUser, get_current_user
from ..models import PluginToggle
from ..services import plugin_store

router = APIRouter(prefix="/plugins", tags=["插件"])


@router.get("", summary="我的插件（含内置插件）")
async def list_plugins(user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    return await plugin_store.list_plugins(user.id)


@router.post("/install", summary="上传 ZIP 安装插件（只接受声明式提示词包）")
async def install_plugin(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    data = await file.read()
    try:
        return await plugin_store.install_plugin(user.id, file.filename or "plugin.zip", data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/{plugin_id}", summary="启用/停用插件")
async def toggle_plugin(
    plugin_id: int,
    payload: PluginToggle,
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    result = await plugin_store.set_enabled(user.id, plugin_id, payload.enabled)
    if not result:
        raise HTTPException(status_code=404, detail="插件不存在")
    return result


@router.delete("/{plugin_id}", summary="卸载插件")
async def remove_plugin(plugin_id: int, user: CurrentUser = Depends(get_current_user)) -> dict:
    if not await plugin_store.delete_plugin(user.id, plugin_id):
        raise HTTPException(status_code=404, detail="插件不存在")
    return {"message": "插件已卸载"}
