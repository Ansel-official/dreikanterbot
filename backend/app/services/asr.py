"""本地 Whisper 语音转文字。

默认使用 faster-whisper（CTranslate2 实现的 OpenAI Whisper，加载同一套 base 权重，
CPU int8 下更快），也兼容官方 openai-whisper 包。模型首次使用时才懒加载，
缓存目录由 WHISPER_CACHE_DIR 指定（docker compose 中挂载为持久 volume）。
"""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

from ..config import settings

logger = logging.getLogger(__name__)


class AsrUnavailable(Exception):
    pass


class AsrError(Exception):
    pass


_engine: str | None = None
_model: Any = None
_load_lock = asyncio.Lock()
_run_lock = asyncio.Semaphore(1)


def detect_engine() -> str | None:
    """按配置和已安装依赖决定引擎，不触发模型加载。"""
    requested = (settings.asr_engine or "auto").strip().lower()
    if requested == "disabled":
        return None
    if requested == "fast":
        requested = "faster"
    if requested in {"faster", "openai"}:
        module = "faster_whisper" if requested == "faster" else "whisper"
        return requested if importlib.util.find_spec(module) else None
    if importlib.util.find_spec("faster_whisper"):
        return "faster"
    if importlib.util.find_spec("whisper"):
        return "openai"
    return None


def engine_name() -> str:
    return detect_engine() or "disabled"


def _load_model_sync(engine: str) -> Any:
    cache_dir = Path(settings.whisper_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("XDG_CACHE_HOME", str(cache_dir))
    if engine == "faster":
        from faster_whisper import WhisperModel

        logger.info("加载 faster-whisper 模型 %s（缓存 %s）", settings.asr_model, cache_dir)
        return WhisperModel(
            settings.asr_model,
            device="cpu",
            compute_type="int8",
            download_root=str(cache_dir),
        )
    import whisper  # type: ignore[import-not-found]

    logger.info("加载 openai-whisper 模型 %s（缓存 %s）", settings.asr_model, cache_dir)
    return whisper.load_model(settings.asr_model, download_root=str(cache_dir))


def _transcribe_sync(path: str, engine: str) -> dict:
    language = (settings.asr_language or "").strip() or None
    if engine == "faster":
        segments, info = _model.transcribe(
            path,
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        raw_parts: list[str] = []
        segment_list: list[dict] = []
        for seg in segments:
            raw_parts.append(seg.text)
            text = (seg.text or "").strip()
            if text:
                segment_list.append(
                    {"start": round(float(seg.start), 2), "end": round(float(seg.end), 2), "text": text}
                )
        return {
            "text": "".join(raw_parts).strip(),
            "language": getattr(info, "language", None) or language,
            "duration": round(float(getattr(info, "duration", 0.0) or 0.0), 2),
            "segments": segment_list[:200],
        }

    result = _model.transcribe(path, language=language, fp16=False)
    raw_parts = []
    segment_list = []
    for seg in result.get("segments") or []:
        raw_parts.append(str(seg.get("text", "")))
        text = str(seg.get("text", "")).strip()
        if text:
            segment_list.append(
                {
                    "start": round(float(seg.get("start", 0.0)), 2),
                    "end": round(float(seg.get("end", 0.0)), 2),
                    "text": text,
                }
            )
    duration = 0.0
    if segment_list:
        duration = segment_list[-1]["end"]
    return {
        "text": "".join(raw_parts).strip(),
        "language": result.get("language") or language,
        "duration": duration,
        "segments": segment_list[:200],
    }


async def _ensure_model(engine: str) -> None:
    global _model, _engine
    if _model is not None and _engine == engine:
        return
    async with _load_lock:
        if _model is not None and _engine == engine:
            return
        try:
            _model = await asyncio.to_thread(_load_model_sync, engine)
            _engine = engine
        except Exception as exc:  # noqa: BLE001
            _model = None
            _engine = None
            logger.exception("Whisper 模型加载失败")
            raise AsrError(
                "语音模型加载失败。首次使用需下载 Whisper base 模型，请检查服务器网络/"
                "HF_ENDPOINT 镜像配置，或提前预热模型缓存。"
            ) from exc


async def transcribe_file(path: str | Path, *, timeout: int | None = None) -> dict:
    engine = detect_engine()
    if engine is None:
        raise AsrUnavailable(
            "服务端未安装/未启用 Whisper。请安装 faster-whisper 或 openai-whisper，"
            "并把 ASR_ENGINE 设为 auto/faster/openai。"
        )
    await _ensure_model(engine)

    async def _run() -> dict:
        async with _run_lock:
            return await asyncio.to_thread(_transcribe_sync, str(path), engine)

    try:
        result = await asyncio.wait_for(_run(), timeout=timeout or settings.asr_timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise AsrError("语音转写超时，请缩短音频长度后重试") from exc
    except AsrError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("Whisper 转写失败")
        raise AsrError("语音转写失败，请确认音频格式后重试") from exc

    result["engine"] = engine
    return result
