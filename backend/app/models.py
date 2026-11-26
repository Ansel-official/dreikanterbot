"""REST / WebSocket 的 Pydantic 数据契约。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .security import validate_password_policy

Role = Literal["admin", "member", "guest"]
Mode = Literal["chat", "reasoner"]


class UserOut(BaseModel):
    id: int
    username: str
    role: Role
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None = None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserOut


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$")
    password: str = Field(min_length=8, max_length=72)
    role: Role = "member"

    @field_validator("username")
    @classmethod
    def _lower_username(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        validate_password_policy(value)
        return value


class PasswordChange(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=72)

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        validate_password_policy(value)
        return value


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=72)

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        validate_password_policy(value)
        return value


class BootstrapRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$")
    password: str = Field(min_length=8, max_length=72)

    @field_validator("username")
    @classmethod
    def _lower_username(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        validate_password_policy(value)
        return value


class SessionCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    mode: Mode = "chat"


class SessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("标题不能为空")
        return value


class SessionOut(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    last_message: str | None = None
    last_message_at: datetime | None = None
    is_deleted: bool = False
    mode: Mode = "chat"


class AttachmentMeta(BaseModel):
    name: str
    size: int = 0
    mime: str | None = None
    text_chars: int = 0


class MessageOut(BaseModel):
    id: int
    session_id: int
    role: Literal["user", "assistant", "system"]
    content: str
    reasoning: str = ""
    mode: Mode = "chat"
    attachments: list[AttachmentMeta] = Field(default_factory=list)
    parent_id: int | None = None
    status: str = "complete"
    created_at: datetime
    usage: dict | None = None


class MessagePage(BaseModel):
    items: list[MessageOut]
    has_more: bool
    next_before_id: int | None = None


class UserPage(BaseModel):
    items: list[UserOut]
    total: int
    page: int
    page_size: int


class UserCreateAdmin(RegisterRequest):
    pass


class UserUpdateAdmin(BaseModel):
    role: Role | None = None
    is_active: bool | None = None


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("名称不能为空")
        return value


class ApiKeyOut(BaseModel):
    id: int
    name: str
    key_prefix: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None = None


class ApiKeyCreated(ApiKeyOut):
    key: str


class AISettingsUpdate(BaseModel):
    api_key: str | None = Field(default=None, max_length=500)
    base_url: str | None = Field(default=None, max_length=500)
    model_chat: str | None = Field(default=None, max_length=120)
    model_reasoner: str | None = Field(default=None, max_length=120)
    context_window: int | None = Field(default=None, ge=4096, le=2_000_000)
    max_output_tokens: int | None = Field(default=None, ge=256, le=131_072)
    temperature: float | None = Field(default=None, ge=0, le=2)
    clear_key: bool = False


class PluginToggle(BaseModel):
    enabled: bool


class MemoryUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    folder: str | None = Field(default=None, max_length=255)
    tags: list[str] | None = None


class MemoryCloudUpdate(BaseModel):
    base_url: str = Field(min_length=8, max_length=500)
    username: str = Field(min_length=1, max_length=200)
    password: str | None = Field(default=None, max_length=500)
    remote_path: str = Field(default="dreikanterbot", max_length=255)
    enabled: bool = True


class UsageOut(BaseModel):
    role: Role
    used: int
    limit: int | None
    remaining: int | None
    resets_at: datetime


class AsrSegment(BaseModel):
    start: float
    end: float
    text: str


class AsrResponse(BaseModel):
    text: str
    language: str | None = None
    duration: float | None = None
    engine: str
    segments: list[AsrSegment] = Field(default_factory=list)


class FileExtractResponse(BaseModel):
    name: str
    size: int
    mime: str | None = None
    text: str
    text_chars: int
    truncated: bool = False
    note: str | None = None


class ImportResponse(BaseModel):
    imported_sessions: int
    imported_messages: int
    session_ids: list[int]
    continue_session_id: int | None = None
    skipped_messages: int = 0


class AdminStats(BaseModel):
    users_total: int
    users_by_role: dict[str, int]
    sessions_total: int
    messages_total: int
    usage_today: int
    recent_users: list[UserOut]
    daily_usage: list[dict]


class HealthResponse(BaseModel):
    status: str
    version: str
    database: bool
    redis: bool
    deepseek_configured: bool
    asr_engine: str | None = None


class MessageResponse(BaseModel):
    message: str
