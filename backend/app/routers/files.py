"""文件导入：把用户上传的文档解析为可送入模型的文本。"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from ..config import settings
from ..deps import CurrentUser, client_ip, get_current_user
from ..models import FileExtractResponse
from ..services.file_extract import FileExtractionError, extract_file
from ..services.rate_limit import RateLimitExceeded, enforce_ip_rate

router = APIRouter(prefix="/files", tags=["文件"])
logger = logging.getLogger(__name__)


@router.post(
    "/extract",
    response_model=FileExtractResponse,
    summary="解析文件为文本（文档/表格/PDF/代码/ZIP）",
)
async def extract_upload(
    request: Request,
    file: UploadFile = File(..., description="任意常见文档、表格、代码或压缩包"),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    try:
        await enforce_ip_rate("file-extract", client_ip(request), limit=30, window_seconds=60)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="文件解析过于频繁，请稍后再试",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc

    data = await file.read(settings.max_file_bytes + 1)
    filename = file.filename or "附件"
    content_type = file.content_type
    await file.close()
    if len(data) > settings.max_file_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"文件不能超过 {settings.max_file_mb}MB",
        )
    if not data:
        raise HTTPException(status_code=400, detail="文件为空")

    try:
        result = await asyncio.to_thread(
            extract_file,
            filename,
            data,
            content_type,
            settings.max_file_text_chars,
        )
    except FileExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("文件解析失败 user=%s name=%s", user.id, filename)
        raise HTTPException(status_code=500, detail="文件解析失败") from exc

    logger.info(
        "文件解析 user=%s name=%s bytes=%s chars=%s",
        user.id,
        result["name"],
        len(data),
        result["text_chars"],
    )
    return result
