# Dreikanterbot · 极简多端 AI 助手

[![CI](https://github.com/Ansel-official/dreikanterbot/actions/workflows/ci.yml/badge.svg)](https://github.com/Ansel-official/dreikanterbot/actions/workflows/ci.yml)

> 面向团队的极简 AI 对话应用：**PostgreSQL 持久化、WebSocket 流式输出、PWA 多端同步、本地 Whisper 语音输入、JWT + 角色权限、完整 REST API 与一键 Docker 部署**。

本项目是一套可直接部署的生产级脚手架，默认使用 DeepSeek 官方 `deepseek-chat`（128K 上下文），也可以按需替换模型或接入其他 OpenAI 兼容网关。

---

## 目录

- [1. 功能清单](#1-功能清单)
- [2. 系统架构](#2-系统架构)
- [3. 目录结构](#3-目录结构)
- [4. 快速开始](#4-快速开始)
- [5. 环境变量](#5-环境变量)
- [6. 账号、角色与配额](#6-账号角色与配额)
- [7. API 与 WebSocket 协议](#7-api-与-websocket-协议)
- [8. 数据库设计](#8-数据库设计)
- [9. 本地开发](#9-本地开发)
- [10. PWA 与多端](#10-pwa-与多端)
- [11. 安全设计](#11-安全设计)
- [12. 运维手册](#12-运维手册)
- [13. Cloudflare 部署](#13-cloudflare-部署)
- [14. 扩展点](#14-扩展点)
- [15. 已知限制](#15-已知限制)
- [16. 上线验收清单](#16-上线验收清单)

---

## 1. 功能清单

| 模块 | 能力 |
|---|---|
| 对话 | WebSocket 流式输出、Markdown/表格、代码块复制、停止生成、失败重试（重新发送） |
| 模式 | 极速（`deepseek-chat`）/ 深度思考（`deepseek-reasoner`）；推理内容流式展示、进度条、可折叠 |
| 文件 | 对话中直接上传 PDF、DOCX、PPTX、XLSX、CSV、文本、代码与 ZIP；最多 5 个/条，解析为上下文 |
| 导入 | 导入 DeepSeek 官方导出的 JSON，重建历史并直接「继续聊」；兼容常见 conversations/messages 结构 |
| 下载 | 安装为 PWA（iPhone/iPad/Android/桌面）；GitHub Release 提供 Web 包与完整部署包 |
| 持久化 | 用户消息、附件文本与 AI 占位消息同事务落库；生成中每 ~0.75 秒增量落库；断线后生成继续完成 |
| 会话 | 新建、切换、重命名、软删除、回收站恢复、按更新时间排序、消息游标分页 |
| 导出 | 单会话 / 全量导出为 JSON 或 Markdown，中文不转义；JSON 保留附件与推理字段 |
| 账号 | JWT 登录（30 天）、管理员创建账号、禁用/启用、角色调整、重置密码、修改自己的密码 |
| 权限 | `admin` / `member` / `guest`；用户列表与账号创建仅管理员 |
| 配额 | Redis 每日计数：guest 100 次、member 1000 次、admin 不限；聊天与 ASR 共用额度 |
| 限流 | 登录 IP 60 次/5 分钟 + 同账号 10 次/5 分钟、ASR 20 次/分钟/IP、文件 30 次/分钟/IP、导入 5 次/分钟/IP、WS 会话生成锁 |
| 语音 | 本地 Whisper（base，中文）转写；浏览器录音、上传、自动回填输入框 |
| UI | Apple 风格极简界面、SF 系统字体、浅/深色、桌面/平板/手机响应式 |
| PWA | manifest、Service Worker 静态缓存、离线打开界面、添加到主屏幕、设备建议与安装引导 |
| 多端 | 同一账号在电脑/平板/手机登录，全部历史从服务端读取 |
| 对外接口 | RESTful + 自动 OpenAPI（`/docs`）、个人 API Key、管理员密钥审计 |
| 运维 | Docker Compose 四服务、一键脚本、健康检查、PostgreSQL 备份脚本、Release 自动打包 |

---

## 2. 系统架构

```text
┌──────────────┐     HTTPS / WSS      ┌──────────────────────────────┐
│ 浏览器 / PWA  │ ───────────────────> │ Nginx（frontend 容器，:80/:443）│
└──────────────┘                      │  ├─ 静态站点 + SPA 回退          │
                                      │  ├─ /api/*  → backend:8000     │
                                      │  └─ /ws/*   → WebSocket 升级    │
                                      └──────────────┬───────────────┘
                                                     │
                                      ┌──────────────▼───────────────┐
                                      │ FastAPI（backend 容器）        │
                                      │  ├─ JWT / API Key / RBAC      │
                                      │  ├─ REST: 会话、消息、导出…    │
                                      │  ├─ WebSocket 流式生成         │
                                      │  ├─ 本地 Whisper ASR          │
                                      │  └─ 每日配额（Redis）          │
                                      └───────┬──────────────┬───────┘
                                              │              │
                                  ┌───────────▼───┐   ┌──────▼─────────┐
                                  │ PostgreSQL 15 │   │ Redis 7        │
                                  │ 用户/会话/消息 │   │ 配额/黑名单/锁  │
                                  └───────────────┘   └────────────────┘
                                              │
                                     ┌────────▼────────┐
                                     │ DeepSeek 官方 API │
                                     │ api.deepseek.com │
                                     └─────────────────┘
```

### 为什么对话不会丢

1. 收到用户消息后，**同一个数据库事务**中写入 `user` 消息 + 空的 `assistant` 占位消息（`status=streaming`），提交后才开始调用 DeepSeek。
2. 生成过程中每约 0.75 秒把已生成文本 `UPDATE` 到消息行；异常/停止/完成时再写最终状态与 token 用量。
3. 浏览器断线**不会取消**后台生成任务，回复仍会写完整；重新连接后前端会从服务端重新同步。
4. 所有会话列表、消息历史、软删除状态都在 PostgreSQL，任何设备登录都能读到同一份数据。

> 注：进程被强制杀死时，最多丢失最后一次增量刷新（<1 秒）的文本；用户消息不会丢。计划内重启请先等待生成结束或使用 `docker compose stop backend`。

---

## 3. 目录结构

```text
dreikanterbot/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI 入口、生命周期、中间件、健康检查
│   │   ├── config.py             # Pydantic Settings（.env）
│   │   ├── database.py           # asyncpg 连接池、自动建表、管理员引导
│   │   ├── redis_client.py       # Redis 连接与降级
│   │   ├── security.py           # bcrypt、JWT、API Key
│   │   ├── deps.py               # 鉴权依赖 / 当前用户 / 客户端 IP
│   │   ├── models.py             # Pydantic 请求响应模型
│   │   ├── serializers.py        # asyncpg Record → JSON
│   │   ├── cli.py                # 运维 CLI：重置密码 / 创建账号
│   │   ├── routers/
│   │   │   ├── auth.py           # 登录、登出、引导、改密
│   │   │   ├── sessions.py       # 会话 CRUD、消息分页、导出
│   │   │   ├── chat_ws.py        # WebSocket 流式对话（核心）
│   │   │   ├── asr.py            # 语音转文字
│   │   │   ├── files.py          # PDF/Word/Excel/PPT/代码/ZIP 解析
│   │   │   ├── imports.py        # DeepSeek 官方对话导入
│   │   │   ├── keys.py           # 个人 API Key
│   │   │   ├── usage.py          # 配额查询
│   │   │   └── admin.py          # 用户管理、统计、密钥审计
│   │   └── services/
│   │       ├── deepseek.py       # 上下文拼接、极速/深度思考、流式推理
│   │       ├── file_extract.py   # 文件文本提取
│   │       ├── conversation_import.py # 官方/通用 JSON 对话解析
│   │       ├── asr.py            # faster-whisper / openai-whisper
│   │       ├── rate_limit.py     # 每日配额、IP 限流、JWT 黑名单、会话锁
│   │       └── usage.py          # usage_logs 写入
│   ├── tests/                    # pytest：单元测试 + PostgreSQL/Redis 集成测试
│   ├── requirements-core.txt    # 不含 Whisper 的核心依赖（含文件解析）
│   ├── requirements-asr.txt     # faster-whisper
│   ├── requirements-dev.txt     # 核心依赖 + pytest/ruff
│   ├── requirements.txt         # 生产镜像依赖（core + ASR）
│   ├── pyproject.toml            # pytest / ruff 配置
│   ├── Dockerfile
│   └── .dockerignore
├── .github/workflows/
│   ├── ci.yml                    # GitHub Actions：后端测试 + 前端构建
│   └── release.yml               # tag 自动打包并发布 Release
├── frontend/
│   ├── src/
│   │   ├── App.jsx / main.jsx
│   │   ├── styles.css            # Apple 风格 + 深浅主题 + 响应式
│   │   ├── api/client.js         # axios、token、错误处理、下载
│   │   ├── hooks/                # 认证、主题、WebSocket、录音、PWA 安装
│   │   └── components/           # 登录、侧边栏、消息、推理面板、文件/导入/设备弹窗
│   ├── public/
│   │   ├── manifest.webmanifest
│   │   ├── sw.js                 # Service Worker
│   │   └── icons/                # PWA / iOS 图标
│   ├── nginx/                    # 安全头、路由、HTTPS 片段
│   ├── nginx.conf                # HTTP 站点（默认）
│   ├── Dockerfile                # node 构建 → nginx 运行
│   └── package.json
├── docs/
│   ├── CLOUDFLARE.md             # Cloudflare 生产配置指南（约 700 行）
│   └── DEVICES.md                # 设备建议、PWA 安装与下载包说明
├── scripts/
│   ├── backup.sh                 # PostgreSQL 备份 + 保留策略
│   └── generate_icons.py         # 重新生成 PWA 图标
├── certs/README.md               # Cloudflare Origin Certificate 放置说明
├── docker-compose.yml            # db / redis / backend / frontend
├── docker-compose.https.yml      # 可选：源站 443 + Origin 证书
├── .env.example
├── deploy.sh
└── README.md
```

---

## 4. 快速开始

### 4.1 前置条件

- Linux / macOS / WSL（Windows 也可用 Docker Desktop）
- Docker Engine 24+ 与 Docker Compose v2
- 一个 DeepSeek API Key（<https://platform.deepseek.com/api_keys>）
- 服务器建议：2 vCPU / 4 GB RAM 起步；启用 Whisper 建议 4 vCPU / 8 GB RAM（首次会下载 ~150 MB base 模型）

### 4.2 一键部署（推荐）

```bash
cd dreikanterbot
chmod +x deploy.sh scripts/backup.sh
./deploy.sh
```

`deploy.sh` 会：

1. 从 `.env.example` 生成 `.env`（权限 600）；
2. 自动生成 `SECRET_KEY`、PostgreSQL 密码、管理员初始密码；
3. 交互式询问 `DEEPSEEK_API_KEY`（可留空稍后补）；
4. 校验 Compose 配置、构建镜像、启动四个服务；
5. 等待 `/api/health` 通过，打印访问地址与管理员账号密码。

默认访问地址：<http://服务器IP/>（或 `APP_PORT` 指定端口）。

> 如果 `certs/origin.pem` 与 `certs/origin.key` 存在，脚本会自动使用
> `docker-compose.https.yml`，同时监听 443。

### 4.3 手动部署

```bash
cp .env.example .env
# 必改：DEEPSEEK_API_KEY / SECRET_KEY / POSTGRES_PASSWORD / ADMIN_PASSWORD
# SECRET_KEY 生成：openssl rand -hex 32

docker compose pull
docker compose build
docker compose up -d
docker compose ps
curl -fsS http://127.0.0.1/api/health
```

从日志确认管理员初始化：

```bash
docker compose logs backend | grep 管理员
```

如果 `.env` 中的 `ADMIN_PASSWORD` 在首次启动时为空，也可以调用一次性引导接口：

```bash
curl -X POST http://127.0.0.1/api/auth/bootstrap \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"Admin-123456"}'
```

### 4.4 首次登录

1. 浏览器打开部署域名；
2. 使用 `.env` 的 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 登录；
3. 打开右上角 **管理控制台 → 用户 → 创建账号**，为成员分配账号；
4. 立即在 **设置 → 账号** 修改管理员密码。

登录 API 示例：

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"你的密码"}' | jq -r .access_token)

curl -s http://127.0.0.1/api/auth/me -H "Authorization: Bearer $TOKEN"
```

### 4.5 HTTPS / Cloudflare

- 本地 HTTP 测试：直接 `docker compose up -d`。
- 生产：按 [docs/CLOUDFLARE.md](docs/CLOUDFLARE.md) 配置 DNS、Full (strict)、WAF、限速、缓存。
- 源站 HTTPS：把 Cloudflare Origin Certificate 放到：

```text
certs/origin.pem
certs/origin.key
```

然后重新运行 `./deploy.sh`。它会自动叠加 `docker-compose.https.yml`，Nginx 监听 443。

手动启动 HTTPS：

```bash
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d
```

> Cloudflare 的 SSL 模式必须是 **Full (strict)**，源站无效证书会报 526。

---

## 5. 环境变量

全部配置见 [.env.example](.env.example)。核心项：

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `DEEPSEEK_API_KEY` | 是（聊天） | — | DeepSeek 官方 Key，仅后端使用，不会下发浏览器 |
| `SECRET_KEY` | 是 | — | JWT 签名密钥，`openssl rand -hex 32` |
| `DATABASE_URL` | 是 | — | asyncpg 连接串；Compose 内会覆盖为 `db:5432` |
| `REDIS_URL` | 是 | — | Redis 连接串；Compose 内为 `redis:6379/0` |
| `POSTGRES_USER/PASSWORD/DB` | 是 | chatbot | Compose 数据库初始化参数 |
| `APP_PORT` | 否 | 80 | 前端对外端口 |
| `HTTPS_PORT` | 否 | 443 | 启用 `docker-compose.https.yml` 时对外 TLS 端口 |
| `CORS_ORIGINS` | 否 | localhost | 允许的浏览器来源，逗号分隔；同源部署不依赖它 |
| `ACCESS_TOKEN_EXPIRE_DAYS` | 否 | 30 | JWT 有效期 |
| `ADMIN_USERNAME` | 否 | admin | 首次启动创建的管理员 |
| `ADMIN_PASSWORD` | 首次 | — | 首次启动创建管理员；数据库已有管理员时不会覆盖 |
| `ALLOW_BOOTSTRAP` | 否 | true | 是否允许 `/api/auth/bootstrap` |
| `BOOTSTRAP_TOKEN` | 否 | — | 设置后 bootstrap 需带 `X-Bootstrap-Token` |
| `GUEST_DAILY_LIMIT` | 否 | 100 | 访客每日 AI 调用次数 |
| `MEMBER_DAILY_LIMIT` | 否 | 1000 | 成员每日 AI 调用次数 |
| `DEEPSEEK_MODEL` | 否 | deepseek-chat | 极速模式模型 |
| `DEEPSEEK_REASONER_MODEL` | 否 | deepseek-reasoner | 深度思考模式模型 |
| `DEEPSEEK_MAX_TOKENS` | 否 | 4096 | 极速模式单次回复最大 token |
| `DEEPSEEK_REASONER_MAX_TOKENS` | 否 | 8192 | 深度思考模式单次回复最大 token |
| `DEEPSEEK_CONTEXT_CHARS` | 否 | 120000 | 极速模式历史裁剪字符预算 |
| `DEEPSEEK_REASONER_CONTEXT_CHARS` | 否 | 60000 | 深度思考模式历史裁剪字符预算 |
| `MAX_FILE_MB` | 否 | 20 | 单个上传文件上限 |
| `MAX_FILE_TEXT_CHARS` | 否 | 80000 | 单个文件解析文本上限 |
| `MAX_ATTACHMENT_COUNT` | 否 | 5 | 单条消息附件数上限 |
| `MAX_IMPORT_MB` | 否 | 20 | DeepSeek 对话导入 JSON 上限 |
| `SYSTEM_PROMPT` | 否 | 内置 | 系统提示词 |
| `ASR_ENGINE` | 否 | auto | `auto/faster/openai/disabled` |
| `ASR_MODEL` | 否 | base | Whisper 模型规格 |
| `ASR_LANGUAGE` | 否 | zh | 转写语言，留空自动检测 |
| `MAX_AUDIO_MB` | 否 | 20 | 上传音频上限 |
| `WHISPER_CACHE_DIR` | 否 | /models/whisper | 模型缓存（Compose 已挂载 named volume） |
| `HF_ENDPOINT` | 否 | hf-mirror.com | HuggingFace 镜像，国内加速 |
| `APP_TIMEZONE` | 否 | Asia/Shanghai | 配额重置与统计使用的时区 |

---

## 6. 账号、角色与配额

| 角色 | 登录 | 创建账号/查看用户 | 每日 AI 次数 | 管理台 |
|---|---|---|---|---|
| `admin` | ✅ | ✅ | 不限 | ✅ |
| `member` | ✅ | ❌ | 1000（可配） | ❌ |
| `guest` | ✅ | ❌ | 100（可配） | ❌ |

- 公开的 `POST /api/auth/register` 也要求管理员 JWT，防止匿名注册。
- 首次管理员由 `ADMIN_USERNAME/ADMIN_PASSWORD` 在数据库空管理员时创建；也支持一次性 `/api/auth/bootstrap`。
- 管理员不能禁用/降级自己，系统始终保留至少一个启用管理员。
- 配额按自然日（`APP_TIMEZONE`）在 Redis 原子计数；Redis 故障时降级为进程内计数（单 worker 有效）。
- 聊天与语音识别共用同一个每日配额；管理员不计数。
- JWT 登出会把 `jti` 加入 Redis 黑名单；修改密码 / 管理员重置密码会把用户 `token_version + 1`，该账号所有旧 token 立即失效。

---

## 7. API 与 WebSocket 协议

### 7.1 认证

```http
Authorization: Bearer <JWT>
```

也支持 API Key：

```http
Authorization: Bearer sk-chat-xxxxxxxx
```

完整 OpenAPI：<http://localhost/docs>（生产 https://你的域名/docs）
ReDoc：`/redoc`；OpenAPI JSON：`/openapi.json`。

### 7.2 REST 接口一览

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/auth/login` | 公开 | 登录，返回 30 天 JWT |
| POST | `/api/auth/register` | admin | 创建账号（兼容旧接口） |
| POST | `/api/auth/bootstrap` | 公开+条件 | 系统无用户时创建第一个管理员 |
| GET | `/api/auth/me` | 登录 | 当前用户 |
| GET | `/api/auth/verify` | 登录 | 校验 token |
| POST | `/api/auth/logout` | 登录 | JWT 加入黑名单 |
| POST | `/api/auth/change-password` | 登录 | 修改密码并续签 token |
| GET | `/api/sessions` | 登录 | 会话列表，`include_deleted` 可选 |
| POST | `/api/sessions` | 登录 | 新建空会话（前端通常首条消息时自动创建） |
| GET | `/api/sessions/{id}` | 登录 | 会话详情 |
| PATCH | `/api/sessions/{id}` | 登录 | 重命名 |
| DELETE | `/api/sessions/{id}` | 登录 | 软删除 |
| POST | `/api/sessions/{id}/restore` | 登录 | 从回收站恢复 |
| GET | `/api/sessions/{id}/messages` | 登录 | 消息历史，`before_id` + `limit` 游标分页 |
| GET | `/api/sessions/{id}/export?format=json\|markdown` | 登录 | 导出单会话 |
| GET | `/api/sessions/export?format=json\|markdown` | 登录 | 导出全部会话 |
| POST | `/api/asr` | 登录 | 上传音频，返回 `{text, language, duration, engine, segments}` |
| POST | `/api/files/extract` | 登录 | 上传文件，返回解析文本、截断标记与说明 |
| POST | `/api/imports/deepseek` | 登录 | 导入 DeepSeek 官方/通用 JSON 对话，返回可继续会话 |
| GET | `/api/usage/me` | 登录 | 今日配额 |
| GET | `/api/usage/me/history?days=14` | 登录 | 个人用量历史 |
| GET | `/api/keys` | 登录 | 我的 API Key 列表 |
| POST | `/api/keys` | 登录 | 创建 API Key（明文仅一次） |
| DELETE | `/api/keys/{id}` | 登录 | 吊销 |
| GET | `/api/admin/users` | admin | 用户搜索/筛选/分页 |
| POST | `/api/admin/users` | admin | 创建账号 |
| PATCH | `/api/admin/users/{id}` | admin | 改角色/启停 |
| DELETE | `/api/admin/users/{id}` | admin | 禁用账号（软删除） |
| POST | `/api/admin/users/{id}/reset-password` | admin | 重置密码 |
| GET | `/api/admin/stats` | admin | 用户/会话/消息/调用统计 |
| GET | `/api/admin/keys` | admin | 全站 API Key 审计 |
| DELETE | `/api/admin/keys/{id}` | admin | 吊销任意 Key |
| GET | `/api/health` | 公开 | DB/Redis/DeepSeek/ASR 健康状态 |
| GET | `/api/version` | 公开 | 版本信息 |

### 7.3 WebSocket

连接：

```text
wss://你的域名/ws/chat?token=<JWT>
```

浏览器会在连接关闭码 `4401`（鉴权失败）或 `4403`（Origin 拒绝）时停止重连；其他原因自动指数退避重连。

客户端 → 服务端：

```json
{"type":"chat","session_id":123,"content":"你好","client_id":"可选幂等 id","mode":"chat","attachments":[]}
{"type":"chat","session_id":123,"content":"","mode":"reasoner","attachments":[{"name":"brief.pdf","size":12345,"mime":"application/pdf","text":"解析后的文本…"}]}
{"type":"stop"}
{"type":"ping"}
```

- `session_id` 为 `null` 时服务端自动创建会话，并通过 `session_created` 返回。
- `mode`：`chat`（极速，默认）或 `reasoner`（深度思考，DeepSeek R1）。
- `attachments`：最多 5 个，文本总计最多 60K 字符；内容会保存到消息并拼进模型上下文。

服务端 → 客户端：

| type | 说明 |
|---|---|
| `ready` | 连接就绪，含 user、quota、model、ai_configured |
| `quota` | 消费后的每日额度 |
| `session_created` | 新会话已创建（含 `mode`） |
| `user_message` | 用户消息已落库（含附件元数据；带 `client_id` 替换乐观消息） |
| `assistant_start` | AI 占位消息已落库（含 `mode`） |
| `reasoning_delta` | 深度思考增量 `{message_id, content}` |
| `reasoning_done` | 思考阶段结束，携带完整 reasoning |
| `delta` | 回答流式增量 `{message_id, content}` |
| `assistant_done` | 完成/停止/失败，携带最终消息、reasoning 与 usage |
| `error` | `{code, message, message_id?, quota?}` |
| `ping` | 服务端每 20 秒心跳（客户端回 `pong`） |

服务端在连接断开后仍会完成生成并落库；前端重连后会重新拉取当前会话消息。

---

## 8. 数据库设计

启动时自动执行 `CREATE TABLE IF NOT EXISTS`，并对旧库做 `ADD COLUMN IF NOT EXISTS` 兼容升级。

### `users`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | BIGSERIAL | 主键 |
| `username` | VARCHAR(64) UNIQUE | 统一小写 |
| `password_hash` | TEXT | bcrypt（cost 12） |
| `role` | VARCHAR(16) | admin/member/guest |
| `is_active` | BOOLEAN | 禁用后立即无法登录 |
| `token_version` | INTEGER | 改密/重置/禁用时 +1，使该用户全部 JWT 失效 |
| `created_at` / `updated_at` | TIMESTAMPTZ | |
| `last_login_at` | TIMESTAMPTZ | 最近登录 |

### `chat_sessions`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | BIGSERIAL | 主键 |
| `user_id` | BIGINT FK | 所属用户 |
| `title` | VARCHAR(200) | 默认“新对话”，首条消息自动命名 |
| `mode` | VARCHAR(16) | chat / reasoner，决定后续消息使用的模型 |
| `created_at` / `updated_at` | TIMESTAMPTZ | 侧边栏按更新时间排序 |
| `is_deleted` | BOOLEAN | 软删除（回收站） |

### `messages`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | BIGSERIAL | 主键 |
| `session_id` | BIGINT FK | 所属会话 |
| `role` | VARCHAR(16) | user/assistant |
| `content` | TEXT | 消息正文；流式期间持续更新 |
| `reasoning` | TEXT | 深度思考内容；仅 reasoner 模式可能非空 |
| `mode` | VARCHAR(16) | chat / reasoner |
| `attachments` | JSONB | 附件元数据与解析文本；API 列表默认不返回 text |
| `parent_id` | BIGINT FK | 用户消息指向上一条消息；AI 消息指向触发它的用户消息 |
| `status` | VARCHAR(16) | complete/streaming/stopped/error |
| `usage` | JSONB | DeepSeek token 用量 |
| `created_at` | TIMESTAMPTZ | |

### 其他表

- `api_keys`：仅存 SHA-256 摘要，明文创建时展示一次；支持吊销。
- `usage_logs`：每次聊天/ASR 的 token 与时间，管理员统计与后续计费扩展。

索引：`(user_id, updated_at)`、`(session_id, id)`、`usage_logs(user_id, created_at)` 等。

---

## 9. 本地开发

### 9.1 启动基础设施

```bash
# 只启动 PostgreSQL 和 Redis
docker compose up -d db redis
```

### 9.2 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 关键：本地开发连 127.0.0.1，而不是容器名 db
export DATABASE_URL="postgresql://chatbot:你的POSTGRES密码@127.0.0.1:5432/chatbot"
export REDIS_URL="redis://127.0.0.1:6379/0"
export WHISPER_CACHE_DIR="./models/whisper"
# 可选：export DEEPSEEK_API_KEY=...
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

注意：本机未安装 `faster-whisper` 时 ASR 会返回 503；聊天与其余接口不受影响。
默认使用 faster-whisper（CTranslate2 实现，加载同一套 OpenAI Whisper base 权重）。如果必须使用官方 `openai-whisper` 包，可额外执行 `pip install openai-whisper` 并设置 `ASR_ENGINE=openai`；官方包依赖 PyTorch，镜像体积会显著增大。

### 9.3 前端

```bash
cd frontend
pnpm install                        # 或 npm install
pnpm dev                            # http://localhost:5173
```

Vite 已配置 `/api` 与 `/ws` 代理到 `http://127.0.0.1:8000`。
默认 `CORS_ORIGINS` 已包含 `http://localhost:5173`。

### 9.4 ASR 模型预热（可选）

```bash
docker compose exec backend python - <<'PY'
from faster_whisper import WhisperModel
WhisperModel("base", download_root="/models/whisper")
print("whisper base ready")
PY
```

网络受限时在 `.env` 设置 `HF_ENDPOINT=https://hf-mirror.com` 后重建/重启 backend。

### 9.5 测试与 CI

后端测试分两层：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# 单元测试（不需要数据库）
pytest tests/test_core.py -q

# 完整测试：先准备可丢弃的 PostgreSQL/Redis，再运行
export TEST_DATABASE_URL="postgresql://chatbot:change-me@127.0.0.1:5432/chatbot_test"
export TEST_REDIS_URL="redis://127.0.0.1:6379/0"
export RUN_INTEGRATION=1
pytest -q
ruff check app tests
```

集成测试会验证：建表、管理员种子、登录、用户管理、会话 CRUD、WebSocket 流式对话（mock DeepSeek）、消息落库、JSON/Markdown 导出、API Key 生命周期。**测试库名必须包含 `test`，测试会 DROP 业务表。**

GitHub Actions（[.github/workflows/ci.yml](.github/workflows/ci.yml)）会在每次 push/PR 时启动 PostgreSQL 15 + Redis 7，执行上述后端测试和前端生产构建。

---

## 10. PWA 与多端

- `manifest.webmanifest` 提供 192/512/maskable 图标、standalone 显示模式、“新建对话”和“继续 DeepSeek 对话”快捷方式。
- `public/sw.js`：
  - 预缓存应用壳与图标；
  - `/assets/*`、`/icons/*` 缓存优先；
  - 页面导航网络优先，离线回退 `index.html`；
  - `/api/*` 与 `/ws/*` **永不缓存**，避免读到旧对话。
- 安装方式：
  - Android Chrome：浏览器菜单 → 安装应用 / 添加到主屏幕；
  - iPhone / iPad Safari：分享 → 添加到主屏幕；
  - 桌面 Chrome/Edge：地址栏安装图标；macOS Safari：文件 → 添加到程序坞。
- 麦克风与 Service Worker 需要 **HTTPS**（localhost 除外）。
- 同一账号在任意设备登录后，会话列表与消息均从服务端读取；删除/重命名也会同步。
- 应用内 **下载与设备** 面板会自动识别当前设备并给出安装建议。

### 10.1 直接下载包体

每次推送 `v*` 标签，Release 工作流会生成：

| 包体 | 内容 | 适合 |
|---|---|---|
| `dreikanterbot-web-<版本>.zip` | 已构建的 `dist/` | 部署到同源 HTTPS 静态站点，或做二次分发 |
| `dreikanterbot-deploy-<版本>.zip` | 完整源码 + Compose + Nginx/Cloudflare 文档 | 部署到自己的服务器 |

下载页：<https://github.com/Ansel-official/dreikanterbot/releases>

### 10.2 设备建议

完整矩阵（推荐机型、浏览器版本、服务端规格、网络要求、能力边界）见
**[docs/DEVICES.md](docs/DEVICES.md)**。简要建议：

| 设备 | 推荐 | 浏览器 |
|---|---|---|
| iPhone | iPhone 12+ / iOS 16.4+ | Safari 17+ |
| iPad | iPadOS 16.4+，横屏更佳 | Safari 17+ |
| Android | 4GB RAM / Android 10+ | Chrome 120+ |
| Windows | 8GB RAM / Win10+ | Edge 120+ / Chrome 120+ |
| macOS | macOS 13+ | Safari 17+ / Chrome |
| 服务端 | 2 vCPU / 4GB（不含语音）；4 vCPU / 8GB（含 Whisper） | Docker Compose |

> PWA 是当前默认的“安装包”：无需应用商店，iPhone/iPad/Android/桌面都能获得独立图标和全屏体验。原生 APK/IPA/EXE 需要平台签名证书，当前 Release 提供 Web 与部署包。

---

## 11. 安全设计

- 密码 bcrypt cost 12；策略：≥8 位、同时含字母与数字、≤72 字节。
- JWT HS256，30 天；登出加入 Redis 黑名单；改密/重置密码通过 `token_version` 让该用户全部旧 token 失效；禁用账号立即生效（每次请求查 DB）。
- WebSocket 通过 query `token` 鉴权；校验 Origin；错误 token 返回 4401。
- CORS 仅允许 `CORS_ORIGINS`；Nginx 安全头含 CSP、HSTS、X-Frame-Options、nosniff、Permissions-Policy。
- API Key 只存 SHA-256，可随时吊销；管理端看不到明文。
- 登录限流、ASR IP 限速、每日配额、会话生成锁；上游错误不泄露 Key。
- 上传音频限制 20MB、类型白名单、临时文件用后删除。
- Docker：后端非 root 用户运行；PostgreSQL/Redis 不映射宿主机端口；仅 frontend 暴露 80/443。
- 生产启动会拒绝默认 `SECRET_KEY`。
- 建议额外：Cloudflare WAF/限速、SSH 仅办公网、定期备份、`/docs` IP 白名单（见 Cloudflare 文档）。

---

## 12. 运维手册

### 12.1 启动 / 停止 / 状态

```bash
./deploy.sh                 # 首次或更新后（自动构建）
./deploy.sh --no-build      # 只重启
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend
docker compose restart backend
docker compose stop
docker compose down         # 保留 named volumes
docker compose down -v      # ⚠️ 删除数据库与 Redis 数据，不可恢复
```

启用 HTTPS 时，Compose 命令要带两个文件（或让 `deploy.sh` 自动处理）：

```bash
docker compose -f docker-compose.yml -f docker-compose.https.yml ps
```

### 12.2 创建账号

方式一（推荐）：管理员登录 → 右上角 **管理控制台 → 用户 → 创建账号**，选择角色并设置初始密码。

方式二（API）：

```bash
curl -X POST http://127.0.0.1/api/admin/users \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"Alice-2026","role":"member"}'
```

用户名规则：3–32 位，字母/数字开头，可含 `._-`；创建时统一转小写。

### 12.3 重置密码

- 管理员：管理控制台 → 用户 → 重置密码。重置会让该用户所有已登录设备立即失效，需要用新密码重新登录。管理员自己的密码请到「设置 → 账号」修改。
- 用户自己：设置 → 账号 → 修改密码；旧 token 立即失效，当前会话自动续签，其他设备需要重新登录。
- 忘记管理员密码时用容器内 CLI 重置（交互输入，不写入 shell history）：

```bash
docker compose exec backend python -m app.cli reset-password --username admin
```

管理员全部丢失且无法登录时，也可以直接创建一个新管理员：

```bash
docker compose exec backend python -m app.cli create-user --username rescue --role admin
```

首次部署完成后，可以从 `.env` 中删除 `ADMIN_PASSWORD`（数据库已有管理员，不会再次创建）。

### 12.4 数据库备份与恢复

备份（`pg_dump` + gzip + 14 天保留）：

```bash
./scripts/backup.sh
# 或指定目录/保留天数
BACKUP_DIR=/data/backups RETENTION_DAYS=30 ./scripts/backup.sh
```

定时任务示例：

```cron
0 3 * * * cd /opt/dreikanterbot && ./scripts/backup.sh >> backups/backup.log 2>&1
```

恢复（会 DROP 并重建对象，务必先停后端）：

```bash
docker compose stop backend
gunzip -c backups/postgres-20261123-030000.sql.gz \
  | docker compose exec -T db psql -U chatbot -d chatbot
docker compose start backend
```

验证备份：

```bash
gzip -t backups/postgres-*.sql.gz
docker compose exec -T db psql -U chatbot -d chatbot -c "SELECT count(*) FROM messages;"
```

Redis 只存配额/黑名单/锁，不是业务数据；`redis_data` volume 会保留。若丢失 Redis，仅配额计数与登出黑名单重置。

### 12.5 健康检查与日志

```bash
curl -fsS http://127.0.0.1/api/health
curl -fsS http://127.0.0.1/healthz        # Nginx 边缘检查，不查 DB

docker compose exec backend python -c "import app; print(app.__version__)"
docker compose exec db psql -U chatbot -d chatbot -c '\dt'
docker compose exec db psql -U chatbot -d chatbot -c 'SELECT count(*) FROM messages;'
```

日志驱动已限制为 `10m × 3` 轮转；长期日志建议接入 Loki/ELK。

### 12.6 升级

```bash
./scripts/backup.sh
git pull                         # 或替换代码
docker compose build
docker compose up -d
```

数据库结构通过启动时的 `CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS` 平滑升级；破坏性迁移需自行编写 SQL。

### 12.7 常见故障

| 症状 | 排查 |
|---|---|
| 页面 502 / API 502 | `docker compose ps`；`logs backend`；backend 健康检查是否通过 |
| 聊天提示“未配置 API Key” | `.env` 的 `DEEPSEEK_API_KEY` 为空；改完 `docker compose up -d backend` |
| 401 频繁 | JWT 过期/被黑名单；重新登录；检查服务器时间 |
| 429 额度不足 | 查看 `/api/usage/me`；管理员可在 Redis 或等次日重置；检查 `GUEST/MEMBER_DAILY_LIMIT` |
| WebSocket 一直重连 | Nginx `/ws/` 升级头、Cloudflare WebSocket、证书；浏览器控制台看关闭码 |
| ASR 503 | 未安装 Whisper 或模型未下载；看 backend 日志 `HF_ENDPOINT` |
| ASR 502 | 音频格式/时长；whisper 推理失败；检查 ffmpeg |
| 管理员密码无效 | 数据库已有管理员时 `ADMIN_PASSWORD` 不会覆盖；用原密码或数据库重置 |
| Cloudflare 526 | 源站证书无效 / 未启用 `docker-compose.https.yml`；检查 Full (strict) |
| 静态资源旧版本 | 清 Cloudflare 缓存；确认 `/sw.js`、`/index.html` 未被缓存；见 Cloudflare 文档 |
| 数据库连不上 | `POSTGRES_PASSWORD` 与 `DATABASE_URL` 不一致；特殊字符需 URL 编码（推荐使用 `deploy.sh` 生成的十六进制密码） |

---

## 13. Cloudflare 部署

完整步骤见 **[docs/CLOUDFLARE.md](docs/CLOUDFLARE.md)**，包含 DNS、Full (strict)、Origin CA、WAF 表达式、限速表、Bot/DDoS、缓存规则、WebSocket、上传限制、Turnstile 与验证清单。

最小上线顺序：

1. 域名 NS 接入 Cloudflare，添加 `A chat → 源站 IP`，**橙色云**；
2. 源站只放行 Cloudflare IP 段的 80/443，SSH 仅办公网；
3. 生成 Origin Certificate → 放入 `certs/origin.pem` / `certs/origin.key` → `./deploy.sh`；
4. Cloudflare SSL/TLS 选 **Full (strict)**，开启 Always Use HTTPS、TLS 1.3、最低 TLS 1.2；
5. 缓存规则：`/api/*`、`/ws/*`、`/docs`、`/openapi.json` **Bypass**；`/assets/*` 长缓存；`/sw.js`、`/manifest.webmanifest`、`/index.html` 不缓存；
6. WAF：登录限速 5 次/分钟/IP、ASR 10 次/分钟/IP、WS 握手 30 次/分钟、管理员路径限制办公出口、拦截 `.env`/`.git` 扫描；
7. 验证：`curl -I https://你的域名/` 检查 HSTS；浏览器 DevTools 确认 WSS 101；Lighthouse 检查 PWA。

> Cloudflare 免费版 WAF 限速能力有限（1 条规则、10 秒窗口）；如需完整规则请升级 Pro/Business，或依赖后端 Redis 每日配额 + Nginx 限流。

---

## 14. 扩展点

- **新增 REST 模块**：在 `backend/app/routers/` 新建 `APIRouter`，在 `main.py` 注册；自动进入 `/docs`。
- **接入其他系统**：用个人 API Key 调用 `/api/sessions`、`/api/sessions/{id}/messages`；或新增 webhook/队列。
- **多实例水平扩展**：当前 WebSocket 生成任务在进程内，必须 `--workers 1`。扩展方案：生成任务落到独立 worker，通过 Redis Pub/Sub 把 delta 广播给持有连接的实例；会话锁已用 Redis，可复用。
- **换模型/网关**：改 `DEEPSEEK_BASE_URL` 与 `DEEPSEEK_MODEL` 即可（OpenAI 兼容协议）。
- **SSO/OIDC**：在 `auth.py` 增加回调，签发同样的 JWT；业务代码只依赖 `CurrentUser`。
- **对象存储导出**：导出接口目前直接返回文件流，可改为后台任务 + S3 预签名 URL。
- **计费**：`usage_logs` 已有 token 明细，可加单价表与月度账单。

---

## 15. 已知限制

1. **单 backend worker**：为了在断线后继续生成，WebSocket 任务保存在进程内；Docker CMD 固定 `--workers 1`。不要直接水平扩容。
2. **进程崩溃保护窗口**：助手内容每 ~0.75 秒增量写入，强制杀进程最多丢失不足 1 秒的文本；完成/停止/出错时立即写最终状态。
3. **JWT 无 refresh token**：30 天内有效；登出会黑名单当前 token，改密/重置密码/禁用会通过 `token_version` 让该用户所有旧 token 失效。
4. **Whisper CPU 推理**：base 模型在 2–4 vCPU 上单路转写约需数秒；首次请求会下载模型。长音频受 `MAX_AUDIO_MB=20` 限制。
5. **上下文裁剪**：极速模式默认最多 12 万字符，深度思考模式 6 万字符；超长对话早期内容不会进入模型上下文（但数据库仍完整保存）。
6. **回收站无自动清理**：软删除会话永久保留，需要时手动写 SQL/管理脚本清理。
7. **PWA 离线能力**：离线只能打开界面与缓存静态资源；新消息必须联网。Service Worker 不会缓存 API。
8. **Cloudflare 免费版限速有限**：边缘规则能力随套餐变化，账号级额度以 Redis 为准。
9. **文件识别边界**：图片仅记录文件信息，当前文本模型不做视觉识别；扫描版 PDF 若没有文本层，需要先 OCR 再上传。
10. **官方导出格式会变化**：导入器按常见 JSON 字段做宽松解析；DeepSeek 若调整导出结构，需要扩展 `conversation_import.py`。
11. **没有原生安装包**：Release 提供 Web 包和部署包；APK/IPA/EXE 需要平台签名证书，当前以 PWA 安装为主。

---

## 16. 上线验收清单

- [ ] `.env` 已改掉所有默认密码，`SECRET_KEY` 为随机值，文件权限 600
- [ ] `curl -fsS https://域名/api/health` 返回 `status: ok`
- [ ] 管理员登录成功，创建 member 账号并能登录
- [ ] 发送消息：用户气泡立即出现、AI 逐字输出、刷新页面后历史完整
- [ ] 切换“深度思考”模式：能看到推理进度条与展开/折叠的思考内容
- [ ] 上传 PDF/Word/Excel/代码文件：解析成功，模型能引用附件内容
- [ ] 导入 DeepSeek 官方 JSON：历史重建成功，点“继续聊”能继续上下文
- [ ] 生成中刷新/切网：重连后消息从服务端恢复，无重复
- [ ] 另一台设备登录同一账号，能看到同一会话
- [ ] 新建/重命名/删除/回收站恢复均正常
- [ ] 导出 JSON 与 Markdown 可用且中文正常
- [ ] 语音输入授权麦克风 → 识别 → 回填输入框（HTTPS 下）
- [ ] PWA 可“添加到主屏幕”，断网后仍能打开壳
- [ ] 下载与设备面板能识别当前设备，Release 包可下载
- [ ] 手机 Safari/Chrome 布局正常，输入框、发送按钮、侧边栏可用
- [ ] 管理员可创建用户、禁用用户、重置密码；非管理员访问 `/api/admin/*` 返回 403
- [ ] guest/member 配额按日生效（可临时把限额调小验证）
- [ ] `/docs` 可访问（建议 Cloudflare 限制办公网）
- [ ] Cloudflare Full (strict) 生效、HSTS 只有一个头、`/api/*` 不被缓存
- [ ] DB 备份脚本成功、恢复流程演练过
- [ ] 服务器时间同步（NTP），否则 JWT 会异常
