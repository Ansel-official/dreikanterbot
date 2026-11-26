"""记忆库的本地文件存储与检索。

文件落在 memory_dir/<user_id>/ 下，数据库只存元数据和可检索文本。
这样下载不依赖数据库大字段，导出/云同步也能直接复用原文件。
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..config import settings
from ..database import get_pool
from .file_extract import FileExtractionError, extract_file

logger = logging.getLogger(__name__)

_UNSAFE = re.compile(r"[^\w.\-（）()\u4e00-\u9fff]+", re.UNICODE)


def memory_root() -> Path:
    return Path(settings.memory_dir).expanduser().resolve()


def _safe_name(name: str) -> str:
    base = Path(name or "未命名文件").name[:180] or "未命名文件"
    cleaned = _UNSAFE.sub("_", base).strip("._")
    return cleaned or "未命名文件"


def _kind_for(suffix: str, mime: str | None) -> str:
    if suffix in {".md", ".markdown"}:
        return "note"
    if suffix in {".json", ".yaml", ".yml"}:
        return "data"
    if suffix in {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cpp", ".c", ".h"}:
        return "code"
    if (mime or "").startswith("image/"):
        return "image"
    if suffix in {".pdf", ".docx", ".pptx", ".xlsx", ".csv"}:
        return "document"
    return "file"


def public_item(row: Any) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "kind": row["kind"],
        "mime": row["mime"],
        "size": int(row["size"] or 0),
        "text_chars": int(row["text_chars"] or 0),
        "tags": list(row["tags"] or []),
        "folder": row["folder"] or "",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "download_url": f"/api/memory/{row['id']}/download",
    }


async def _total_bytes(user_id: int) -> int:
    value = await get_pool().fetchval(
        "SELECT COALESCE(SUM(size), 0) FROM memory_items WHERE user_id = $1", user_id
    )
    return int(value or 0)


async def save_memory(
    user_id: int,
    *,
    filename: str,
    data: bytes,
    mime: str | None = None,
    folder: str = "",
    tags: list[str] | None = None,
) -> dict:
    if not data:
        raise ValueError("文件为空")
    if len(data) > settings.max_memory_mb * 1024 * 1024:
        raise ValueError(f"单个文件不能超过 {settings.max_memory_mb} MB")
    total = await _total_bytes(user_id)
    if total + len(data) > settings.max_memory_total_mb * 1024 * 1024:
        raise ValueError(f"记忆库总容量不能超过 {settings.max_memory_total_mb} MB，请先删除旧文件")

    safe = _safe_name(filename)
    suffix = Path(safe).suffix.lower()
    try:
        extracted = await asyncio.to_thread(
            extract_file, safe, data, mime, settings.max_memory_text_chars
        )
        text = extracted.get("text") or ""
    except FileExtractionError as exc:
        text = ""
        logger.info("记忆库文件未能提取文本：%s", exc)
    except Exception:  # noqa: BLE001
        logger.exception("记忆库文件解析失败")
        text = ""

    digest = hashlib.sha256(data).hexdigest()
    root = memory_root() / str(user_id)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{uuid4().hex}{suffix}"
    await asyncio.to_thread(path.write_bytes, data)

    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO memory_items
            (user_id, title, kind, mime, size, text_chars, text_content,
             storage_path, sha256, tags, folder)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11)
        RETURNING *
        """,
        user_id,
        safe,
        _kind_for(suffix, mime),
        mime,
        len(data),
        len(text),
        text,
        str(path),
        digest,
        tags or [],
        (folder or "").strip()[:255],
    )
    return public_item(row)


async def get_item(user_id: int, item_id: int) -> Any | None:
    return await get_pool().fetchrow(
        "SELECT * FROM memory_items WHERE id = $1 AND user_id = $2", item_id, user_id
    )


async def delete_item(user_id: int, item_id: int) -> bool:
    row = await get_item(user_id, item_id)
    if not row:
        return False
    await get_pool().execute("DELETE FROM memory_items WHERE id = $1", item_id)
    path = Path(row["storage_path"] or "")
    try:
        if path.is_file():
            await asyncio.to_thread(path.unlink)
    except OSError:
        logger.warning("删除记忆库文件失败：%s", path)
    return True


async def export_zip(user_id: int) -> Path:
    rows = await get_pool().fetch(
        "SELECT * FROM memory_items WHERE user_id = $1 ORDER BY id", user_id
    )
    fd, temp_name = tempfile.mkstemp(prefix="dreikanterbot-memory-", suffix=".zip")
    os.close(fd)
    path = Path(temp_name)
    try:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            manifest = []
            for row in rows:
                item = {
                    "id": row["id"],
                    "title": row["title"],
                    "kind": row["kind"],
                    "mime": row["mime"],
                    "size": int(row["size"] or 0),
                    "tags": list(row["tags"] or []),
                    "folder": row["folder"] or "",
                    "created_at": row["created_at"].isoformat(),
                }
                manifest.append(item)
                source = Path(row["storage_path"] or "")
                if source.is_file():
                    archive.write(source, f"files/{row['id']}_{_safe_name(row['title'])}")
            archive.writestr(
                "manifest.json",
                json.dumps(
                    {"app": "Dreikanterbot", "version": 3, "exported_at": datetime.now(timezone.utc).isoformat(), "items": manifest},
                    ensure_ascii=False,
                    indent=2,
                ),
            )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


async def import_zip(user_id: int, data: bytes) -> dict:
    if len(data) > settings.max_memory_total_mb * 1024 * 1024:
        raise ValueError("压缩包过大")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("压缩包损坏或不是 ZIP") from exc
    imported = 0
    skipped = 0
    for info in archive.infolist():
        if info.is_dir() or info.filename.startswith("__MACOSX/"):
            continue
        if info.file_size > settings.max_memory_mb * 1024 * 1024:
            skipped += 1
            continue
        name = Path(info.filename).name
        if not name or name == "manifest.json":
            continue
        try:
            raw = archive.read(info)
            await save_memory(user_id, filename=name, data=raw, mime=None)
            imported += 1
        except Exception:  # noqa: BLE001
            logger.exception("导入记忆库文件失败：%s", info.filename)
            skipped += 1
    return {"imported": imported, "skipped": skipped}
