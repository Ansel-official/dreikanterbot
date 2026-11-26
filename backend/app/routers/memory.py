"""记忆库：文件上传、检索、下载、导出/导入，以及 WebDAV 个人云端同步。"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from ..config import settings
from ..database import get_pool
from ..deps import CurrentUser, get_current_user
from ..models import MemoryCloudUpdate, MemoryUpdate
from ..services import memory_store
from ..services.secrets import decrypt_secret, encrypt_secret
from ..services.webdav import (
    WebDAVError,
    client_for,
    ensure_path,
    get_file,
    list_files,
    put_file,
    validate_url,
)

router = APIRouter(prefix="/memory", tags=["记忆库"])
logger = logging.getLogger(__name__)


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = [item.strip()[:40] for item in raw.replace("，", ",").split(",")]
    return [item for item in parts if item][:20]


async def _cloud_row(user_id: int):
    return await get_pool().fetchrow("SELECT * FROM memory_cloud WHERE user_id = $1", user_id)


@router.get("", summary="列出/搜索记忆库")
async def list_memory(
    q: str | None = Query(default=None, max_length=200),
    folder: str | None = Query(default=None, max_length=255),
    kind: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    where = ["user_id = $1"]
    params: list = [user.id]
    if q:
        params.append(f"%{q.strip()}%")
        where.append(f"(title ILIKE ${len(params)} OR text_content ILIKE ${len(params)})")
    if folder:
        params.append(folder.strip())
        where.append(f"folder = ${len(params)}")
    if kind:
        params.append(kind.strip())
        where.append(f"kind = ${len(params)}")
    where_sql = " AND ".join(where)
    pool = get_pool()
    total = int(await pool.fetchval(f"SELECT COUNT(*) FROM memory_items WHERE {where_sql}", *params) or 0)
    params.extend([limit, offset])
    rows = await pool.fetch(
        f"SELECT * FROM memory_items WHERE {where_sql} ORDER BY created_at DESC LIMIT ${len(params)-1} OFFSET ${len(params)}",
        *params,
    )
    used = int(await pool.fetchval("SELECT COALESCE(SUM(size),0) FROM memory_items WHERE user_id = $1", user.id) or 0)
    return {
        "items": [memory_store.public_item(row) for row in rows],
        "total": total,
        "used_bytes": used,
        "limit_bytes": settings.max_memory_total_mb * 1024 * 1024,
    }


@router.post("/upload", summary="上传文件到记忆库并提取文本")
async def upload_memory(
    file: UploadFile = File(...),
    folder: str = Form(default=""),
    tags: str = Form(default=""),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    data = await file.read()
    try:
        item = await memory_store.save_memory(
            user.id,
            filename=file.filename or "未命名文件",
            data=data,
            mime=file.content_type,
            folder=folder[:255],
            tags=_parse_tags(tags),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return item


@router.get("/export", summary="导出整个记忆库为 ZIP")
async def export_memory(
    background: BackgroundTasks,
    user: CurrentUser = Depends(get_current_user),
) -> FileResponse:
    path = await memory_store.export_zip(user.id)
    background.add_task(path.unlink, missing_ok=True)
    return FileResponse(path, filename="dreikanterbot-memory.zip", media_type="application/zip")


@router.post("/import", summary="从 ZIP 导入记忆库")
async def import_memory(
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    data = await file.read()
    try:
        return await memory_store.import_zip(user.id, data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/cloud", summary="读取个人云端配置")
async def get_cloud(user: CurrentUser = Depends(get_current_user)) -> dict:
    row = await _cloud_row(user.id)
    if not row:
        return {"enabled": False, "base_url": "", "username": "", "remote_path": "dreikanterbot", "has_password": False, "last_sync_at": None}
    return {
        "enabled": bool(row["enabled"]),
        "base_url": row["base_url"],
        "username": row["username"],
        "remote_path": row["remote_path"],
        "has_password": bool(row["password_encrypted"]),
        "last_sync_at": row["last_sync_at"],
    }


@router.put("/cloud", summary="保存个人云端配置（密码加密）")
async def save_cloud(payload: MemoryCloudUpdate, user: CurrentUser = Depends(get_current_user)) -> dict:
    try:
        base_url = validate_url(payload.base_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    current = await _cloud_row(user.id)
    encrypted = current["password_encrypted"] if current else ""
    if payload.password:
        encrypted = encrypt_secret(payload.password)
    if not encrypted:
        raise HTTPException(status_code=422, detail="首次配置必须填写应用密码/访问令牌")
    remote_path = "/".join(
        part for part in (payload.remote_path or "dreikanterbot").replace("\\", "/").split("/") if part and part not in {".", ".."}
    )[:255] or "dreikanterbot"
    await get_pool().execute(
        """
        INSERT INTO memory_cloud (user_id, base_url, username, password_encrypted, remote_path, enabled, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, NOW())
        ON CONFLICT (user_id) DO UPDATE SET
            base_url = EXCLUDED.base_url,
            username = EXCLUDED.username,
            password_encrypted = EXCLUDED.password_encrypted,
            remote_path = EXCLUDED.remote_path,
            enabled = EXCLUDED.enabled,
            updated_at = NOW()
        """,
        user.id,
        base_url,
        payload.username.strip(),
        encrypted,
        remote_path,
        payload.enabled,
    )
    return await get_cloud(user)


async def _cloud_client(user_id: int):
    row = await _cloud_row(user_id)
    if not row or not row["enabled"]:
        raise HTTPException(status_code=400, detail="尚未启用个人云端")
    password = decrypt_secret(row["password_encrypted"])
    if not password:
        raise HTTPException(status_code=400, detail="云端密码无法解密，请重新保存配置")
    return client_for(row["base_url"], row["username"], password), row


@router.post("/cloud/test", summary="测试个人云端 WebDAV 连接")
async def test_cloud(user: CurrentUser = Depends(get_current_user)) -> dict:
    client, row = await _cloud_client(user.id)
    try:
        await ensure_path(client, row["base_url"], row["remote_path"])
        files = await list_files(client, f"{row['base_url'].rstrip('/')}/{row['remote_path'].strip('/')}")
        return {"ok": True, "files": len(files), "remote_path": row["remote_path"]}
    except WebDAVError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await client.aclose()


@router.post("/cloud/sync", summary="把本地记忆库上传到个人云端")
async def sync_cloud(user: CurrentUser = Depends(get_current_user)) -> dict:
    client, row = await _cloud_client(user.id)
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM memory_items WHERE user_id = $1 ORDER BY id", user.id)
    uploaded = 0
    try:
        target = await ensure_path(client, row["base_url"], row["remote_path"])
        for item in rows:
            source = Path(item["storage_path"] or "")
            if not source.is_file():
                continue
            remote_name = f"{item['id']}_{memory_store._safe_name(item['title'])}"
            await put_file(
                client,
                f"{target}/{quote(remote_name)}",
                await asyncio.to_thread(source.read_bytes),
                item["mime"] or "application/octet-stream",
            )
            uploaded += 1
        await pool.execute("UPDATE memory_cloud SET last_sync_at = NOW() WHERE user_id = $1", user.id)
        return {"ok": True, "uploaded": uploaded}
    except WebDAVError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await client.aclose()


@router.post("/cloud/pull", summary="从个人云端拉取新文件到记忆库")
async def pull_cloud(user: CurrentUser = Depends(get_current_user)) -> dict:
    client, row = await _cloud_client(user.id)
    pool = get_pool()
    target = f"{row['base_url'].rstrip('/')}/{row['remote_path'].strip('/')}"
    imported = 0
    skipped = 0
    try:
        existing = {
            row["sha256"]
            for row in await pool.fetch("SELECT sha256 FROM memory_items WHERE user_id = $1 AND sha256 IS NOT NULL", user.id)
        }
        for entry in await list_files(client, target):
            if entry["is_dir"] or entry["size"] <= 0:
                continue
            try:
                data = await get_file(client, entry["href"], settings.max_memory_mb * 1024 * 1024)
            except WebDAVError:
                skipped += 1
                continue
            digest = hashlib.sha256(data).hexdigest()
            if digest in existing:
                skipped += 1
                continue
            name = unquote(entry["name"]).split("_", 1)[-1] or "云端文件"
            try:
                await memory_store.save_memory(user.id, filename=name, data=data, mime=None, folder="云端")
                existing.add(digest)
                imported += 1
            except Exception:  # noqa: BLE001
                logger.exception("云端文件导入失败")
                skipped += 1
        await pool.execute("UPDATE memory_cloud SET last_sync_at = NOW() WHERE user_id = $1", user.id)
        return {"ok": True, "imported": imported, "skipped": skipped}
    except WebDAVError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await client.aclose()


@router.get("/{item_id}", summary="读取记忆条目（含全文）")
async def read_memory(item_id: int, user: CurrentUser = Depends(get_current_user)) -> dict:
    row = await memory_store.get_item(user.id, item_id)
    if not row:
        raise HTTPException(status_code=404, detail="记忆条目不存在")
    return {
        **memory_store.public_item(row),
        "text": row["text_content"],
        "truncated": int(row["text_chars"] or 0) >= settings.max_memory_text_chars,
    }


@router.patch("/{item_id}", summary="重命名/移动/打标签")
async def update_memory(item_id: int, payload: MemoryUpdate, user: CurrentUser = Depends(get_current_user)) -> dict:
    row = await memory_store.get_item(user.id, item_id)
    if not row:
        raise HTTPException(status_code=404, detail="记忆条目不存在")
    title = (payload.title or row["title"]).strip()[:255] or row["title"]
    folder = (payload.folder if payload.folder is not None else row["folder"]).strip()[:255]
    tags = payload.tags if payload.tags is not None else list(row["tags"] or [])
    tags = [tag.strip()[:40] for tag in tags if tag.strip()][:20]
    updated = await get_pool().fetchrow(
        "UPDATE memory_items SET title=$1, folder=$2, tags=$3, updated_at=NOW() WHERE id=$4 RETURNING *",
        title,
        folder,
        tags,
        item_id,
    )
    return memory_store.public_item(updated)


@router.delete("/{item_id}", summary="删除记忆条目")
async def delete_memory(item_id: int, user: CurrentUser = Depends(get_current_user)) -> dict:
    if not await memory_store.delete_item(user.id, item_id):
        raise HTTPException(status_code=404, detail="记忆条目不存在")
    return {"message": "已删除"}


@router.get("/{item_id}/download", summary="下载原始文件")
async def download_memory(item_id: int, user: CurrentUser = Depends(get_current_user)) -> FileResponse:
    row = await memory_store.get_item(user.id, item_id)
    if not row:
        raise HTTPException(status_code=404, detail="记忆条目不存在")
    path = Path(row["storage_path"] or "")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="原始文件已丢失")
    return FileResponse(path, filename=row["title"], media_type=row["mime"] or "application/octet-stream")
