"""WebSocket 实时对话。

协议（JSON 文本帧，server -> client 省略自明字段）：
客户端 -> 服务端
  {"type":"chat","session_id":123|null,"content":"...","client_id":"可选"}
  {"type":"stop"}
  {"type":"ping"} / {"type":"pong"}

服务端 -> 客户端
  {"type":"ready","user":{...},"quota":{...},"model":"deepseek-chat","ai_configured":true}
  {"type":"quota","quota":{...}}
  {"type":"session_created","session":{...}}
  {"type":"user_message","message":{...},"client_id":"..."}
  {"type":"assistant_start","message":{...}}           # 已落库的空 assistant 消息
  {"type":"delta","message_id":1,"content":"..."}      # 流式增量
  {"type":"assistant_done","status":"complete|stopped|error","message":{...},"usage":{...}}
  {"type":"error","code":"...","message":"...","message_id":1|null}
  {"type":"ping","ts":...}

持久化策略：
- 收到用户消息的同一个事务里写入 user + 空 assistant 占位消息；
- 生成过程中每 ~0.75 秒把已生成内容 UPDATE 到数据库；
- 完成/停止/出错时再写最终状态与 token 用量；
- 客户端断开不会取消生成任务，后台仍会写完整回复，重连后可拉取历史。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import suppress
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from ..config import settings
from ..database import get_pool
from ..deps import CurrentUser, resolve_user_from_token
from ..serializers import iso, message_public, session_public, user_public
from ..services.ai_config import AIConfig, get_ai_config
from ..services.deepseek import (
    DeepSeekError,
    DeepSeekNotConfigured,
    stream_completion,
)
from ..services.rate_limit import (
    QuotaExceeded,
    acquire_session_lock,
    consume_daily_quota,
    is_token_blacklisted,
    peek_daily_quota,
    release_session_lock,
)
from ..services.usage import log_usage

router = APIRouter(prefix="/ws", tags=["实时对话"])
logger = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 500_000
MAX_ATTACHMENT_TOTAL_CHARS = 2_000_000
LOCK_TTL_SECONDS = 1800
VALID_MODES = {"chat", "reasoner"}


def _normalise_attachments(raw: object) -> list[dict]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        raise ValueError("attachments 必须是数组")
    if len(raw) > settings.max_attachment_count:
        raise ValueError(f"单条消息最多 {settings.max_attachment_count} 个附件")
    attachments: list[dict] = []
    total_chars = 0
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("附件格式不正确")
        name = str(item.get("name") or "附件").strip()[:200] or "附件"
        text = str(item.get("text") or "")
        if len(text) > settings.max_file_text_chars:
            text = text[: settings.max_file_text_chars]
        total_chars += len(text)
        if total_chars > MAX_ATTACHMENT_TOTAL_CHARS:
            raise ValueError("附件文本总长度超过限制，请减少文件")
        try:
            size = max(0, int(item.get("size") or 0))
        except (TypeError, ValueError):
            size = 0
        mime = item.get("mime")
        attachments.append(
            {
                "name": name,
                "size": size,
                "mime": str(mime)[:120] if mime else None,
                "text": text,
            }
        )
    return attachments


def _prompt_content(content: str, attachments: list[dict]) -> str:
    parts: list[str] = []
    if content.strip():
        parts.append(content.strip())
    for attachment in attachments or []:
        text = str(attachment.get("text") or "").strip()
        name = attachment.get("name") or "附件"
        if text:
            parts.append(f"[附件：{name}]\n{text}")
        else:
            parts.append(f"[附件：{name}（二进制文件，未提取到文本）]")
    return "\n\n".join(parts)


def _title_for(content: str, attachments: list[dict]) -> str:
    title = " ".join(content.split())[:30]
    if not title and attachments:
        title = str(attachments[0].get("name") or "附件对话")[:30]
    return title or "新对话"


def _normalise_mode(raw: object, default: str = "chat") -> str:
    mode = str(raw or default)
    return mode if mode in VALID_MODES else default


def _origin_allowed(origin: str | None, host: str | None) -> bool:
    """同源浏览器永远放行；跨域来源必须在 CORS_ORIGINS 白名单内。"""
    if not origin:
        return True  # 非浏览器客户端（curl / 服务端 SDK）
    parsed = urlparse(origin)
    if not parsed.scheme or not parsed.netloc:
        return False
    if host and parsed.netloc == host:
        return True
    return origin.rstrip("/") in settings.cors_origin_list


class ChatConnection:
    def __init__(self, websocket: WebSocket, user: CurrentUser):
        self.ws = websocket
        self.user = user
        self.closed = False
        self.send_lock = asyncio.Lock()
        self.active_task: asyncio.Task | None = None
        self.active_session_id: int | None = None
        self.connection_id = uuid4().hex

    # ------------------------------------------------------------------ I/O
    async def send(self, payload: dict) -> bool:
        if self.closed:
            return False
        try:
            async with self.send_lock:
                await self.ws.send_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            return True
        except (WebSocketDisconnect, RuntimeError, ConnectionError, OSError):
            self.closed = True
            return False

    async def send_error(self, message: str, code: str = "bad_request", **extra) -> None:
        await self.send({"type": "error", "code": code, "message": message, **extra})

    async def _heartbeat(self) -> None:
        """每 20 秒应用层心跳，避免 Cloudflare / Nginx 的空闲连接回收。"""
        try:
            while not self.closed:
                await asyncio.sleep(20)
                if not await self.send({"type": "ping", "ts": int(time.time())}):
                    break
        except asyncio.CancelledError:
            raise

    # ------------------------------------------------------------------ main
    async def run(self) -> None:
        pool = get_pool()
        full_user = await pool.fetchrow("SELECT * FROM users WHERE id = $1", self.user.id)
        quota = await peek_daily_quota(self.user.id, self.user.role)
        ai_config = await get_ai_config(self.user.id)
        await self.send(
            {
                "type": "ready",
                "protocol": "1.0",
                "server_time": iso(datetime.now(timezone.utc)),
                "user": user_public(full_user) if full_user else {"id": self.user.id, "username": self.user.username},
                "quota": quota.to_public(),
                "model": ai_config.model_for("chat"),
                "model_reasoner": ai_config.model_for("reasoner"),
                "provider": ai_config.provider_for("chat"),
                "provider_reasoner": ai_config.provider_for("reasoner"),
                "ai_configured": ai_config.configured,
                "ai_ready": ai_config.ready_for("chat"),
                "reasoner_ready": ai_config.ready_for("reasoner"),
                "ai_source": ai_config.source,
                "ai_key_hint": ai_config.key_hint,
                "context_window": ai_config.context_window,
                "max_output_tokens": ai_config.max_output_tokens,
                "provider_status": ai_config.public()["provider_status"],
                "max_content_chars": MAX_CONTENT_CHARS,
            }
        )

        heartbeat = asyncio.create_task(self._heartbeat())
        try:
            while not self.closed:
                try:
                    raw = await self.ws.receive_text()
                except WebSocketDisconnect:
                    break
                except RuntimeError:
                    break

                try:
                    data = json.loads(raw)
                    if not isinstance(data, dict):
                        raise ValueError("帧必须是 JSON 对象")
                except (json.JSONDecodeError, ValueError):
                    await self.send_error("无法解析的消息格式")
                    continue

                try:
                    await self.handle(data)
                except Exception as exc:  # noqa: BLE001 - 单条消息失败不应断开连接
                    logger.exception("处理 WebSocket 消息失败 user=%s", self.user.id)
                    await self.send_error("服务器处理消息时出现异常", code="internal_error")
                    _ = exc
        finally:
            self.closed = True
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            # 注意：不断开 active_task。客户端断线后生成继续，确保回复完整落库。

    async def handle(self, data: dict) -> None:
        kind = data.get("type")
        if kind == "ping":
            await self.send({"type": "pong", "ts": int(time.time())})
            return
        if kind == "pong":
            return
        if kind == "chat":
            await self.handle_chat(data)
            return
        if kind == "stop":
            await self.handle_stop()
            return
        await self.send_error(f"不支持的消息类型：{kind}", code="unsupported_type")

    # ------------------------------------------------------------------ chat
    async def _identity_valid(self) -> bool:
        """长连接期间重新校验账号状态：禁用、改密、吊销 Key 后应立即停止对话。"""
        pool = get_pool()
        try:
            if self.user.auth_type == "api_key":
                row = await pool.fetchrow(
                    """
                    SELECT k.is_active AS key_active, u.role, u.is_active
                    FROM api_keys k JOIN users u ON u.id = k.user_id
                    WHERE k.id = $1
                    """,
                    self.user.api_key_id,
                )
                if row is None or not row["key_active"] or not row["is_active"]:
                    return False
            else:
                if self.user.token_expires_at and datetime.now(timezone.utc) >= self.user.token_expires_at:
                    return False
                if self.user.jti and await is_token_blacklisted(self.user.jti):
                    return False
                row = await pool.fetchrow(
                    "SELECT role, is_active, token_version FROM users WHERE id = $1",
                    self.user.id,
                )
                if row is None or not row["is_active"]:
                    return False
                if int(row["token_version"]) != int(self.user.token_version or 0):
                    return False
            self.user.role = row["role"]
            return True
        except Exception:  # noqa: BLE001 - 校验失败时拒绝发送，避免绕过权限
            logger.exception("WebSocket 期间账号状态校验失败 user=%s", self.user.id)
            return False

    async def handle_chat(self, data: dict) -> None:
        if self.active_task is not None and not self.active_task.done():
            await self.send_error("上一条回复还在生成中，请先等待完成或点击停止", code="busy")
            return

        if not await self._identity_valid():
            await self.send_error("登录状态已失效，请重新登录", code="session_expired")
            await self.ws.close(code=4401, reason="session expired")
            self.closed = True
            return

        content = data.get("content")
        if content is None:
            content = ""
        if not isinstance(content, str):
            await self.send_error("消息内容格式不正确")
            return
        content = content.strip()
        try:
            attachments = _normalise_attachments(data.get("attachments"))
        except ValueError as exc:
            await self.send_error(str(exc), code="invalid_attachments")
            return
        if not content and not attachments:
            await self.send_error("消息内容不能为空")
            return
        if len(content) > MAX_CONTENT_CHARS:
            await self.send_error(f"单条消息最多 {MAX_CONTENT_CHARS} 字符", code="content_too_long")
            return

        ai_config = await get_ai_config(self.user.id)
        mode_was_explicit = data.get("mode") in VALID_MODES
        requested_mode = _normalise_mode(data.get("mode"))
        if not mode_was_explicit and data.get("session_id") not in (None, ""):
            try:
                existing_mode = await get_pool().fetchval(
                    "SELECT mode FROM chat_sessions WHERE id = $1 AND user_id = $2 AND is_deleted = FALSE",
                    int(data.get("session_id")),
                    self.user.id,
                )
                if existing_mode:
                    requested_mode = _normalise_mode(existing_mode)
            except (TypeError, ValueError):
                pass
        if not ai_config.ready_for(requested_mode):
            provider = ai_config.provider_for(requested_mode)
            model = ai_config.model_for(requested_mode)
            await self.send_error(
                f"当前模型 {model} 所属的 {provider} 还没有 API Key。"
                "前往「设置 → AI 接入」填写，密钥只保存在这台服务器上。",
                code="api_key_required",
                provider=provider,
                model=model,
            )
            await self.send(
                {
                    "type": "ai_required",
                    "message": "配置对应 Provider 的 API Key 后才能发送消息",
                    "provider": provider,
                    "model": model,
                }
            )
            return

        session_id_raw = data.get("session_id")
        session_id: int | None = None
        if session_id_raw not in (None, ""):
            try:
                session_id = int(session_id_raw)
                if session_id <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                await self.send_error("session_id 必须是正整数", code="invalid_session")
                return

        client_id = data.get("client_id")
        client_id = str(client_id)[:64] if client_id else None

        try:
            quota = await consume_daily_quota(self.user.id, self.user.role)
        except QuotaExceeded as exc:
            await self.send(
                {
                    "type": "error",
                    "code": "quota_exceeded",
                    "message": f"今日额度已用完（{exc.quota.limit} 次/天），请明天再试或联系管理员",
                    "quota": exc.quota.to_public(),
                }
            )
            return
        await self.send({"type": "quota", "quota": quota.to_public()})

        lock_owner = f"{self.connection_id}:{uuid4().hex}"
        acquired = await acquire_session_lock(session_id or 0, lock_owner, ttl=LOCK_TTL_SECONDS) if session_id else True
        if not acquired:
            await self.send_error("该会话正在其他设备生成回复，请稍后再试", code="session_busy")
            return

        pool = get_pool()
        new_session_row = None
        mode = requested_mode
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    if session_id is not None:
                        session_row = await conn.fetchrow(
                            """
                            SELECT id, title, mode, is_deleted FROM chat_sessions
                            WHERE id = $1 AND user_id = $2
                            FOR UPDATE
                            """,
                            session_id,
                            self.user.id,
                        )
                        if session_row is None or session_row["is_deleted"]:
                            raise LookupError("会话不存在或已删除")
                        if not mode_was_explicit:
                            mode = _normalise_mode(session_row["mode"])
                    else:
                        title = _title_for(content, attachments)
                        new_session_row = await conn.fetchrow(
                            """
                            INSERT INTO chat_sessions (user_id, title, mode)
                            VALUES ($1, $2, $3)
                            RETURNING *, 0::bigint AS message_count, NULL::text AS last_message,
                                      NULL::timestamptz AS last_message_at
                            """,
                            self.user.id,
                            title,
                            mode,
                        )
                        session_id = new_session_row["id"]
                        if session_id is not None:
                            # 新会话的锁在插入后补上；若此时被抢占则回滚（概率极低）
                            acquired_new = await acquire_session_lock(
                                session_id, lock_owner, ttl=LOCK_TTL_SECONDS
                            )
                            if not acquired_new:
                                raise RuntimeError("新会话锁冲突，请重试")

                    last_message_id = await conn.fetchval(
                        "SELECT id FROM messages WHERE session_id = $1 ORDER BY id DESC LIMIT 1",
                        session_id,
                    )
                    if last_message_id is None:
                        current = await conn.fetchval(
                            "SELECT title FROM chat_sessions WHERE id = $1",
                            session_id,
                        )
                        if current in ("新对话", ""):
                            await conn.execute(
                                "UPDATE chat_sessions SET title = $1 WHERE id = $2",
                                _title_for(content, attachments),
                                session_id,
                            )

                    user_row = await conn.fetchrow(
                        """
                        INSERT INTO messages
                            (session_id, role, content, mode, attachments, parent_id, status)
                        VALUES ($1, 'user', $2, $3, $4, $5, 'complete')
                        RETURNING *
                        """,
                        session_id,
                        content,
                        mode,
                        attachments,
                        last_message_id,
                    )
                    assistant_row = await conn.fetchrow(
                        """
                        INSERT INTO messages
                            (session_id, role, content, mode, parent_id, status)
                        VALUES ($1, 'assistant', '', $2, $3, 'streaming')
                        RETURNING *
                        """,
                        session_id,
                        mode,
                        user_row["id"],
                    )
                    await conn.execute(
                        "UPDATE chat_sessions SET mode = $1, updated_at = NOW() WHERE id = $2",
                        mode,
                        session_id,
                    )
        except LookupError:
            await release_session_lock(session_id or 0, lock_owner)
            await self.send_error("会话不存在或已被删除", code="session_not_found")
            return
        except Exception:  # noqa: BLE001
            logger.exception("创建对话消息失败 user=%s session=%s", self.user.id, session_id)
            if session_id is not None:
                await release_session_lock(session_id, lock_owner)
            await self.send_error("消息保存失败，请稍后重试", code="persist_failed")
            return

        assert session_id is not None
        if new_session_row is not None:
            await self.send({"type": "session_created", "session": session_public(new_session_row)})
        await self.send(
            {
                "type": "user_message",
                "message": message_public(user_row),
                "client_id": client_id,
            }
        )
        await self.send({"type": "assistant_start", "message": message_public(assistant_row)})

        self.active_session_id = session_id
        self.active_task = asyncio.create_task(
            self._stream_reply(
                session_id=session_id,
                user_message_id=user_row["id"],
                assistant_message_id=assistant_row["id"],
                lock_owner=lock_owner,
                mode=mode,
                ai_config=ai_config,
            )
        )
        self.active_task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task) -> None:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            exc = None
        if exc is not None:
            logger.error("生成任务异常退出", exc_info=exc)
        if self.active_task is task:
            self.active_task = None
            self.active_session_id = None

    async def handle_stop(self) -> None:
        task = self.active_task
        if task is None or task.done():
            await self.send_error("当前没有正在生成的回复", code="not_generating")
            return
        task.cancel()
        await self.send({"type": "stopping"})

    # --------------------------------------------------------------- generate
    async def _stream_reply(
        self,
        *,
        session_id: int,
        user_message_id: int,
        assistant_message_id: int,
        lock_owner: str,
        mode: str,
        ai_config: AIConfig | None = None,
    ) -> None:
        pool = get_pool()
        partial = ""
        reasoning_partial = ""
        usage: dict | None = None
        final_status = "error"
        last_persist = time.monotonic()
        reasoning_finished = False
        try:
            rows = await pool.fetch(
                """
                SELECT * FROM (
                    SELECT id, role, content, attachments, status FROM messages
                    WHERE session_id = $1 AND id <= $2
                      AND role IN ('user', 'assistant')
                      AND status IN ('complete', 'stopped')
                      AND (content <> '' OR attachments IS NOT NULL)
                    ORDER BY id DESC LIMIT 10000
                ) recent
                ORDER BY id ASC
                """,
                session_id,
                user_message_id,
            )
            history = []
            for row in rows:
                prompt_content = _prompt_content(row["content"], row["attachments"] or [])
                if prompt_content.strip():
                    history.append({"role": row["role"], "content": prompt_content})

            async for event in stream_completion(history, mode=mode, config=ai_config):
                if event.reasoning:
                    reasoning_partial += event.reasoning
                    await self.send(
                        {
                            "type": "reasoning_delta",
                            "message_id": assistant_message_id,
                            "content": event.reasoning,
                        }
                    )
                    now = time.monotonic()
                    if now - last_persist >= 0.75:
                        await pool.execute(
                            """
                            UPDATE messages
                            SET content = $1, reasoning = $2
                            WHERE id = $3 AND status = 'streaming'
                            """,
                            partial,
                            reasoning_partial,
                            assistant_message_id,
                        )
                        last_persist = now
                if event.content:
                    if reasoning_partial and not reasoning_finished:
                        reasoning_finished = True
                        if not self.closed:
                            await self.send(
                                {
                                    "type": "reasoning_done",
                                    "message_id": assistant_message_id,
                                    "reasoning": reasoning_partial,
                                }
                            )
                    partial += event.content
                    await self.send(
                        {"type": "delta", "message_id": assistant_message_id, "content": event.content}
                    )
                    now = time.monotonic()
                    if now - last_persist >= 0.75:
                        # 流式过程中持续落库，进程崩溃最多丢 0.75 秒文本
                        await pool.execute(
                            """
                            UPDATE messages
                            SET content = $1, reasoning = $2
                            WHERE id = $3 AND status = 'streaming'
                            """,
                            partial,
                            reasoning_partial,
                            assistant_message_id,
                        )
                        last_persist = now
                if event.usage:
                    usage = event.usage

            final_status = "complete"
        except asyncio.CancelledError:
            final_status = "stopped"
            saved = await self._finalize_message(
                assistant_message_id, partial, "stopped", usage, reasoning_partial
            )
            if saved and not self.closed:
                await self.send(
                    {
                        "type": "assistant_done",
                        "status": "stopped",
                        "message": saved,
                        "usage": usage,
                    }
                )
            raise
        except DeepSeekNotConfigured:
            final_status = "error"
            saved = await self._finalize_message(
                assistant_message_id, partial, "error", None, reasoning_partial
            )
            await self.send_error(
                "模型 API Key 未配置或已失效，请前往「设置 → AI 接入」检查",
                code="not_configured",
                message_id=assistant_message_id,
            )
            if saved and not self.closed:
                await self.send(
                    {"type": "assistant_done", "status": "error", "message": saved, "usage": None}
                )
        except DeepSeekError as exc:
            final_status = "error"
            saved = await self._finalize_message(
                assistant_message_id, partial, "error", None, reasoning_partial
            )
            await self.send_error(exc.message, code=exc.code, message_id=assistant_message_id)
            if saved and not self.closed:
                await self.send(
                    {"type": "assistant_done", "status": "error", "message": saved, "usage": None}
                )
        except Exception:  # noqa: BLE001
            logger.exception("生成回复失败 session=%s message=%s", session_id, assistant_message_id)
            final_status = "error"
            saved = await self._finalize_message(
                assistant_message_id, partial, "error", None, reasoning_partial
            )
            await self.send_error(
                "AI 回复生成失败，请稍后重试", code="generation_failed", message_id=assistant_message_id
            )
            if saved and not self.closed:
                await self.send(
                    {"type": "assistant_done", "status": "error", "message": saved, "usage": None}
                )
        finally:
            try:
                if final_status == "complete":
                    saved = await self._finalize_message(
                        assistant_message_id, partial, "complete", usage, reasoning_partial
                    )
                    if saved:
                        await pool.execute(
                            "UPDATE chat_sessions SET updated_at = NOW() WHERE id = $1", session_id
                        )
                        if not self.closed:
                            await self.send(
                                {
                                    "type": "assistant_done",
                                    "status": "complete",
                                    "message": saved,
                                    "usage": usage,
                                }
                            )
            except Exception:  # noqa: BLE001 - 收尾失败不能阻止锁释放
                logger.exception("保存最终回复失败 session=%s", session_id)
            finally:
                try:
                    await release_session_lock(session_id, lock_owner)
                except Exception:  # noqa: BLE001
                    logger.exception("释放会话锁失败 session=%s", session_id)
                tokens = usage or {}
                await log_usage(
                    self.user.id,
                    "chat",
                    int(tokens.get("prompt_tokens", 0) or 0),
                    int(tokens.get("completion_tokens", 0) or 0),
                )

    async def _finalize_message(
        self,
        message_id: int,
        content: str,
        status: str,
        usage: dict | None,
        reasoning: str = "",
    ) -> dict | None:
        try:
            row = await get_pool().fetchrow(
                """
                UPDATE messages
                SET content = $1, status = $2, usage = $3, reasoning = $4
                WHERE id = $5
                RETURNING *
                """,
                content,
                status,
                usage,
                reasoning,
                message_id,
            )
            return message_public(row) if row else None
        except Exception:  # noqa: BLE001
            logger.exception("更新 assistant 消息最终状态失败 message_id=%s", message_id)
            return None


@router.websocket("/chat")
async def websocket_chat(
    websocket: WebSocket,
    token: str | None = Query(default=None, description="登录接口返回的 JWT"),
) -> None:
    origin = websocket.headers.get("origin")
    if not _origin_allowed(origin, websocket.headers.get("host")):
        await websocket.accept()
        await websocket.close(code=4403, reason="origin not allowed")
        return

    if not token:
        await websocket.accept()
        await websocket.close(code=4401, reason="missing token")
        return

    try:
        user = await resolve_user_from_token(token)
    except HTTPException:
        await websocket.accept()
        await websocket.close(code=4401, reason="unauthorized")
        return
    except Exception:  # noqa: BLE001
        logger.exception("WebSocket 鉴权时发生异常")
        await websocket.accept()
        await websocket.close(code=1011, reason="auth backend unavailable")
        return

    await websocket.accept()
    connection = ChatConnection(websocket, user)
    try:
        await connection.run()
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("WebSocket 连接异常 user=%s", user.id)
    finally:
        connection.closed = True
        with suppress(Exception):
            await websocket.close()
