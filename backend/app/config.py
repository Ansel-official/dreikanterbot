"""应用配置：所有配置项均可通过环境变量或 .env 覆盖。"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SYSTEM_PROMPT = (
    "你是 Dreikanterbot，一名严谨、友好的 AI 助手。请使用简体中文回答，表达准确、简洁、可执行；"
    "涉及代码时给出完整可运行的示例，并说明关键步骤。不要编造不确定的事实。"
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- 应用 ----
    app_name: str = "Dreikanterbot"
    environment: str = "production"
    api_prefix: str = "/api"
    log_level: str = "INFO"
    app_timezone: str = "Asia/Shanghai"

    # ---- 安全 / JWT ----
    secret_key: str = "dev-insecure-secret-please-change"
    jwt_algorithm: str = "HS256"
    access_token_expire_days: int = 30
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8080,http://127.0.0.1:8080"
    )
    allowed_hosts: str = ""

    # ---- 数据库 / Redis ----
    database_url: str = "postgresql://chatbot:change-me-strong@127.0.0.1:5432/chatbot"
    redis_url: str = "redis://127.0.0.1:6379/0"
    db_pool_min_size: int = 1
    db_pool_max_size: int = 10

    # ---- 引导管理员 ----
    admin_username: str = "admin"
    admin_password: str = ""
    allow_bootstrap: bool = True
    bootstrap_token: str = ""

    # ---- 每日配额 ----
    guest_daily_limit: int = 100
    member_daily_limit: int = 1000

    # ---- DeepSeek / 模型接入 ----
    # V3 默认要求用户自带 Key（BYOK）。服务端 Key 仅作为可选的兜底，默认关闭。
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_reasoner_model: str = "deepseek-reasoner"
    deepseek_max_tokens: int = 65536
    deepseek_reasoner_max_tokens: int = 65536
    deepseek_temperature: float = 1.0
    # 上下文按 token 预算计算；DeepSeek 官方模型为 128K。
    default_context_window: int = 128_000
    max_context_window: int = 2_000_000
    allow_server_key_fallback: bool = False
    deepseek_timeout_seconds: int = 300
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    # ---- 记忆库 / 个人云端 ----
    memory_dir: str = "./data/memory"
    max_memory_mb: int = 100
    max_memory_total_mb: int = 4096
    max_memory_text_chars: int = 2_000_000
    webdav_timeout_seconds: int = 60

    # ---- 声明式插件 ----
    plugin_dir: str = "./data/plugins"
    max_plugin_mb: int = 10
    max_plugin_files: int = 80
    max_plugin_prompts: int = 50

    # ---- 文件导入 ----
    max_file_mb: int = 100
    max_file_text_chars: int = 2_000_000
    max_attachment_count: int = 10
    max_import_mb: int = 100

    # ---- ASR ----
    asr_engine: str = "auto"  # auto / faster / openai / disabled
    asr_model: str = "base"
    asr_language: str = "zh"
    max_audio_mb: int = 20
    asr_timeout_seconds: int = 180
    whisper_cache_dir: str = "/models/whisper"

    # ---- 前端构建（Vite 读取，后端不使用） ----
    vite_api_base: str = "/api"

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip().rstrip("/")
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @property
    def max_audio_bytes(self) -> int:
        return self.max_audio_mb * 1024 * 1024

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    @property
    def max_import_bytes(self) -> int:
        return self.max_import_mb * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"prod", "production"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
