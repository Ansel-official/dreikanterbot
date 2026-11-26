"""FastAPI 应用入口：生命周期、中间件、路由注册、健康检查。"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .config import settings
from .database import close_db, db_healthy, init_db
from .models import HealthResponse
from .redis_client import close_redis, init_redis, redis_healthy
from .routers import admin, ai_settings, asr, auth, chat_ws, files, imports, keys, memory, plugins, sessions, usage
from .services.asr import engine_name
from .services.deepseek import deepseek_configured

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

INSECURE_SECRETS = {
    "dev-insecure-secret-please-change",
    "please-generate-with-openssl-rand-hex-32",
    "change-me",
}

TAGS_METADATA = [
    {"name": "认证", "description": "JWT 登录、登出、账号创建、改密。Token 有效期 30 天。"},
    {"name": "会话", "description": "会话 CRUD、消息历史游标分页、JSON/Markdown 导出。"},
    {"name": "实时对话", "description": "WebSocket /ws/chat：鉴权、流式输出、断线续存。"},
    {"name": "语音", "description": "本地 Whisper 语音转文字（multipart 上传）。"},
    {"name": "文件", "description": "上传 PDF/Word/Excel/PPT/代码/ZIP 并解析为模型可读文本。"},
    {"name": "导入", "description": "导入 DeepSeek 官方/通用 JSON 对话，导入后可直接继续聊天。"},
    {"name": "AI 接入", "description": "用户自带模型 API Key、模型选择与最大上下文窗口。"},
    {"name": "记忆库", "description": "文件上传、全文检索、下载、导出与 WebDAV 个人云端同步。"},
    {"name": "插件", "description": "声明式插件：提示词/模板包，上传安装、启停，不执行第三方代码。"},
    {"name": "API Key", "description": "为脚本/外部系统创建个人 API Key。"},
    {"name": "管理员", "description": "用户管理、系统统计、密钥审计。仅 admin 角色可用。"},
    {"name": "配额", "description": "每日配额查询与用量历史。"},
    {"name": "系统", "description": "健康检查与版本信息。"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.is_production and settings.secret_key in INSECURE_SECRETS:
        raise RuntimeError(
            "SECRET_KEY 仍是默认占位值。请执行 `openssl rand -hex 32` 生成后写入 .env 再启动。"
        )
    if not settings.deepseek_api_key:
        logger.warning("DEEPSEEK_API_KEY 未配置，聊天接口将返回错误；语音转文字不受影响。")
    if not settings.cors_origin_list:
        logger.warning("CORS_ORIGINS 为空，浏览器跨域请求会被拒绝（同源部署不受影响）。")

    await init_db()
    await init_redis()
    logger.info(
        "%s v%s 启动完成 | env=%s | model=%s | asr=%s",
        settings.app_name,
        __version__,
        settings.environment,
        settings.deepseek_model,
        engine_name(),
    )
    try:
        yield
    finally:
        await close_redis()
        await close_db()
        logger.info("服务已停止，数据库连接已释放")


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description=(
        "Dreikanterbot 后端 API。所有会话与消息持久化在 PostgreSQL，"
        "AI 回复通过 WebSocket 流式推送；支持极速/深度思考、文件解析与对话导入。\n\n"
        "认证方式：`Authorization: Bearer <JWT>` 或 `Authorization: Bearer sk-chat-...`（API Key）。"
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=TAGS_METADATA,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Quota-Limit", "Retry-After"],
)

if settings.allowed_host_list:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.allowed_host_list + ["localhost", "127.0.0.1", "testserver"],
    )

app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
    response.headers.setdefault("Permissions-Policy", "microphone=(self), camera=(), geolocation=()")
    if request.url.path.startswith(settings.api_prefix + "/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("未处理异常 %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请稍后重试"})


app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(ai_settings.router, prefix=settings.api_prefix)
app.include_router(memory.router, prefix=settings.api_prefix)
app.include_router(plugins.router, prefix=settings.api_prefix)
app.include_router(sessions.router, prefix=settings.api_prefix)
app.include_router(keys.router, prefix=settings.api_prefix)
app.include_router(asr.router, prefix=settings.api_prefix)
app.include_router(files.router, prefix=settings.api_prefix)
app.include_router(imports.router, prefix=settings.api_prefix)
app.include_router(usage.router, prefix=settings.api_prefix)
app.include_router(admin.router, prefix=settings.api_prefix)
app.include_router(chat_ws.router)


@app.get("/", include_in_schema=False)
async def root() -> dict:
    return {
        "name": settings.app_name,
        "version": __version__,
        "docs": "/docs",
        "health": f"{settings.api_prefix}/health",
    }


@app.get(
    f"{settings.api_prefix}/health",
    tags=["系统"],
    summary="健康检查",
    response_model=HealthResponse,
)
async def health(response: Response) -> dict:
    db_ok = await db_healthy()
    redis_ok = await redis_healthy()
    asr_engine = engine_name()
    if not db_ok:
        state = "unhealthy"
        response.status_code = 503
    elif not redis_ok:
        state = "degraded"
    else:
        state = "ok"
    return {
        "status": state,
        "version": __version__,
        "database": db_ok,
        "redis": redis_ok,
        "deepseek_configured": deepseek_configured(),
        "asr_engine": asr_engine,
    }


@app.get(f"{settings.api_prefix}/version", tags=["系统"], summary="版本信息")
async def version() -> dict:
    return {
        "name": settings.app_name,
        "version": __version__,
        "model": settings.deepseek_model,
        "environment": settings.environment,
    }
