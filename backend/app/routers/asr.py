"""语音转文字 API：接收浏览器录音，调用本地 Whisper。"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from ..config import settings
from ..deps import CurrentUser, client_ip, get_current_user
from ..models import AsrResponse
from ..services.asr import AsrError, AsrUnavailable, transcribe_file
from ..services.rate_limit import (
    QuotaExceeded,
    RateLimitExceeded,
    consume_daily_quota,
    enforce_ip_rate,
)
from ..services.usage import log_usage

router = APIRouter(prefix="/asr", tags=["语音"])
logger = logging.getLogger(__name__)

_ALLOWED_SUFFIXES = {
    ".webm",
    ".wav",
    ".mp3",
    ".m4a",
    ".mp4",
    ".ogg",
    ".oga",
    ".flac",
    ".aac",
    ".mpeg",
    ".mpga",
}
_ALLOWED_CONTENT_PREFIXES = ("audio/", "video/webm", "video/mp4", "application/octet-stream")


def _safe_suffix(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix in _ALLOWED_SUFFIXES:
        return suffix
    content_type = (upload.content_type or "").split(";")[0].strip().lower()
    mapping = {
        "audio/webm": ".webm",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/ogg": ".ogg",
        "audio/flac": ".flac",
        "video/webm": ".webm",
        "video/mp4": ".mp4",
    }
    return mapping.get(content_type, ".webm")


@router.post("", response_model=AsrResponse, summary="上传音频并返回转写文本")
async def transcribe(
    request: Request,
    file: UploadFile = File(..., description="浏览器录音文件（webm/wav/mp3/m4a 等）"),
    user: CurrentUser = Depends(get_current_user),
) -> dict:
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if not content_type.startswith(_ALLOWED_CONTENT_PREFIXES):
        raise HTTPException(status_code=415, detail=f"不支持的音频类型：{content_type or 'unknown'}")

    try:
        await enforce_ip_rate("asr", client_ip(request), limit=20, window_seconds=60)
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail="语音请求过于频繁，请稍后再试",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc

    try:
        await consume_daily_quota(user.id, user.role)
    except QuotaExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail=f"今日额度已用完（上限 {exc.quota.limit} 次/天），请明天再试或联系管理员",
            headers={"X-Quota-Limit": str(exc.quota.limit)},
        ) from exc

    suffix = _safe_suffix(file)
    tmp_path = ""
    size = 0
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix="asr-") as tmp:
            tmp_path = tmp.name
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > settings.max_audio_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"音频过大，最大允许 {settings.max_audio_mb}MB",
                    )
                tmp.write(chunk)

        if size == 0:
            raise HTTPException(status_code=400, detail="音频文件为空")

        result = await transcribe_file(tmp_path)
        text = (result.get("text") or "").strip()
        await log_usage(user.id, "asr")
        logger.info("ASR user=%s bytes=%s chars=%s engine=%s", user.id, size, len(text), result.get("engine"))
        return {
            "text": text,
            "language": result.get("language"),
            "duration": result.get("duration"),
            "engine": result.get("engine") or "unknown",
            "segments": result.get("segments") or [],
        }
    except AsrUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AsrError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await file.close()
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
