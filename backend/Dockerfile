FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    PORT=8000

# ffmpeg 用于解码浏览器录音；libgomp1 是 ctranslate2 / faster-whisper 的运行时依赖
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg curl libgomp1 tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-core.txt requirements-asr.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY app ./app

# 非 root 运行；Whisper 模型缓存目录需要可写（compose 中挂载 named volume）
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /models/whisper \
    && chown -R appuser:appuser /app /models

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# 注意：WebSocket 生成任务保存在进程内，生产环境必须单 worker。
# 水平扩展需要把生成任务迁移到独立 worker + Redis Pub/Sub，详见 README。
# WS 的 JWT 在 query 中，关闭 uvicorn access log，避免 token 写入日志；访问日志由 Nginx 记录。
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips=*", "--no-access-log"]
