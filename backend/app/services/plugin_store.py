"""声明式插件：只读取 plugin.json 与提示词模板，不执行第三方代码。

插件包格式（ZIP）：
  plugin.json
  README.md（可选）
  prompts/*.md（可选）
plugin.json:
  {"id":"my-pack","name":"我的提示词包","version":"1.0.0",
   "description":"...","author":"...",
   "prompts":[{"title":"...","prompt":"...","mode":"chat"}]}
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from ..config import settings
from ..database import get_pool

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_ALLOWED_SUFFIXES = {".json", ".md", ".txt"}

BUILTIN_PLUGINS: list[dict] = [
    {
        "key": "research-notes",
        "name": "研究笔记",
        "version": "1.0.0",
        "description": "把零散材料整理成可追溯的研究笔记：来源、事实、判断分开写。",
        "author": "Dreikanterbot",
        "prompts": [
            {
                "title": "整理研究材料",
                "prompt": "请把下面的材料整理成研究笔记。分为：已确认事实、来源与日期、存在争议之处、我的判断、下一步需要验证的问题。不要编造来源。\n\n材料：\n",
                "mode": "chat",
            },
            {
                "title": "找出论证漏洞",
                "prompt": "请以审稿人的标准检查下面这段论证：核心主张是什么？证据是否支持主张？有没有反例、偷换概念或因果倒置？最后给出三条最值得补的证据。\n\n论证：\n",
                "mode": "reasoner",
            },
        ],
    },
    {
        "key": "code-review",
        "name": "代码审查",
        "version": "1.0.0",
        "description": "面向生产环境的代码审查清单：正确性、边界、并发、安全、可维护性。",
        "author": "Dreikanterbot",
        "prompts": [
            {
                "title": "严格代码审查",
                "prompt": "请审查下面的代码。先给结论（可合并/需修改/阻塞），再按严重程度列出问题，每条包含：位置、触发条件、后果、修复建议。最后列出缺失的测试。不要泛泛而谈。\n\n代码：\n```\n",
                "mode": "reasoner",
            },
            {
                "title": "解释一段代码",
                "prompt": "请解释下面代码的真实行为，而不是复述语法：输入输出、状态变化、异常路径、复杂度、隐藏副作用。若代码有 bug，直接指出。\n\n代码：\n```\n",
                "mode": "chat",
            },
        ],
    },
    {
        "key": "writing-desk",
        "name": "写作工作台",
        "version": "1.0.0",
        "description": "去掉套话和 AI 腔，保留信息密度；适合说明文、产品文案与长文改写。",
        "author": "Dreikanterbot",
        "prompts": [
            {
                "title": "去 AI 腔改写",
                "prompt": "请改写下面的文字。要求：删掉空泛的过渡句、排比和“首先其次最后”模板；保留事实和限定条件；句子长短交错；不要添加原文没有的信息。改完给出一段 50 字以内的修改说明。\n\n原文：\n",
                "mode": "chat",
            },
            {
                "title": "把草稿变成可发布稿",
                "prompt": "把下面的草稿整理成可直接发布的文章。先判断读者是谁、他们为什么要读，再给标题、导语、正文、结尾。不要用“在这个快速发展的时代”之类的开头。\n\n草稿：\n",
                "mode": "chat",
            },
        ],
    },
]


def builtin_public() -> list[dict]:
    return [
        {
            **item,
            "id": f"builtin:{item['key']}",
            "enabled": True,
            "builtin": True,
            "installed_at": None,
            "prompt_count": len(item["prompts"]),
        }
        for item in BUILTIN_PLUGINS
    ]


def public_plugin(row: Any) -> dict:
    manifest = row["manifest"] or {}
    prompts = manifest.get("prompts") or []
    return {
        "id": row["id"],
        "key": row["plugin_key"],
        "name": row["name"],
        "version": row["version"],
        "description": row["description"],
        "author": row["author"],
        "enabled": bool(row["enabled"]),
        "builtin": bool(row["builtin"]),
        "prompts": prompts,
        "prompt_count": len(prompts),
        "installed_at": row["created_at"],
    }


def _manifest_from_zip(data: bytes) -> tuple[dict, dict[str, bytes]]:
    if len(data) > settings.max_plugin_mb * 1024 * 1024:
        raise ValueError(f"插件包不能超过 {settings.max_plugin_mb} MB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("插件包不是有效 ZIP") from exc
    files: dict[str, bytes] = {}
    manifest: dict | None = None
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/"):
            raise ValueError("插件包包含非法路径")
        if len(files) >= settings.max_plugin_files:
            raise ValueError(f"插件包文件数不能超过 {settings.max_plugin_files}")
        suffix = Path(name).suffix.lower()
        if suffix not in _ALLOWED_SUFFIXES:
            raise ValueError(f"插件包只允许 JSON/Markdown/TXT 文件：{name}")
        raw = archive.read(info)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError(f"插件内单个文件不能超过 2 MB：{name}")
        # 允许根目录或单个顶层目录
        parts = [part for part in name.split("/") if part]
        relative = "/".join(parts[1:]) if len(parts) > 1 and parts[0] not in {"prompts"} else name
        files[relative] = raw
        if relative == "plugin.json" or name.endswith("/plugin.json"):
            try:
                manifest = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("plugin.json 不是有效 UTF-8 JSON") from exc
    if manifest is None:
        raise ValueError("插件包根目录缺少 plugin.json")
    return manifest, files


def validate_manifest(manifest: dict) -> dict:
    if not isinstance(manifest, dict):
        raise ValueError("plugin.json 必须是对象")
    key = str(manifest.get("id") or "").strip().lower()
    if not _ID_RE.match(key):
        raise ValueError("插件 id 只能包含小写字母、数字、点、下划线和短横线（2-64 位）")
    name = str(manifest.get("name") or "").strip()[:120]
    if not name:
        raise ValueError("插件缺少 name")
    version = str(manifest.get("version") or "1.0.0").strip()[:40]
    raw_prompts = manifest.get("prompts") or []
    if not isinstance(raw_prompts, list) or not raw_prompts:
        raise ValueError("插件至少需要一个提示词模板")
    if len(raw_prompts) > settings.max_plugin_prompts:
        raise ValueError(f"提示词模板不能超过 {settings.max_plugin_prompts} 个")
    prompts = []
    for item in raw_prompts:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:80]
        prompt = str(item.get("prompt") or "").strip()
        if not title or not prompt:
            continue
        mode = item.get("mode") if item.get("mode") in {"chat", "reasoner"} else "chat"
        prompts.append({"title": title, "prompt": prompt[:20_000], "mode": mode})
    if not prompts:
        raise ValueError("没有有效的提示词模板（需要 title 与 prompt）")
    return {
        "id": key,
        "name": name,
        "version": version or "1.0.0",
        "description": str(manifest.get("description") or "").strip()[:1000],
        "author": str(manifest.get("author") or "匿名").strip()[:120],
        "prompts": prompts,
        "capabilities": ["prompt"],
    }


async def install_plugin(user_id: int, filename: str, data: bytes) -> dict:
    manifest, files = _manifest_from_zip(data)
    manifest = validate_manifest(manifest)
    root = Path(settings.plugin_dir).expanduser().resolve() / str(user_id) / manifest["id"]
    if root.exists():
        await asyncio.to_thread(shutil.rmtree, root)
    root.mkdir(parents=True, exist_ok=True)
    for name, raw in files.items():
        target = (root / name).resolve()
        if root not in target.parents and target != root:
            raise ValueError("插件包包含非法路径")
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, raw)
    # 写入规范化后的 manifest，后续读取不依赖原包
    await asyncio.to_thread(
        (root / "plugin.json").write_text,
        json.dumps(manifest, ensure_ascii=False, indent=2),
        "utf-8",
    )

    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO plugins
            (owner_id, plugin_key, name, version, description, author, manifest,
             install_path, enabled, builtin)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, TRUE, FALSE)
        ON CONFLICT (owner_id, plugin_key) DO UPDATE SET
            name = EXCLUDED.name,
            version = EXCLUDED.version,
            description = EXCLUDED.description,
            author = EXCLUDED.author,
            manifest = EXCLUDED.manifest,
            install_path = EXCLUDED.install_path,
            enabled = TRUE,
            updated_at = NOW()
        RETURNING *
        """,
        user_id,
        manifest["id"],
        manifest["name"],
        manifest["version"],
        manifest["description"],
        manifest["author"],
        manifest,
        str(root),
    )
    return public_plugin(row)


async def list_plugins(user_id: int) -> list[dict]:
    rows = await get_pool().fetch(
        "SELECT * FROM plugins WHERE owner_id = $1 ORDER BY created_at DESC", user_id
    )
    return builtin_public() + [public_plugin(row) for row in rows]


async def set_enabled(user_id: int, plugin_id: int, enabled: bool) -> dict | None:
    row = await get_pool().fetchrow(
        "UPDATE plugins SET enabled = $1, updated_at = NOW() WHERE id = $2 AND owner_id = $3 RETURNING *",
        enabled,
        plugin_id,
        user_id,
    )
    return public_plugin(row) if row else None


async def delete_plugin(user_id: int, plugin_id: int) -> bool:
    row = await get_pool().fetchrow(
        "SELECT * FROM plugins WHERE id = $1 AND owner_id = $2", plugin_id, user_id
    )
    if not row:
        return False
    await get_pool().execute("DELETE FROM plugins WHERE id = $1", plugin_id)
    path = Path(row["install_path"] or "")
    try:
        if path.is_dir():
            await asyncio.to_thread(shutil.rmtree, path)
    except OSError:
        logger.warning("删除插件目录失败：%s", path)
    return True
