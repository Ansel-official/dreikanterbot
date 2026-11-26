# 本地演示

这个目录让 Dreikanterbot 在没有真实 DeepSeek API Key 的情况下也能完整演示。

`mock_deepseek.py` 实现了一个最小 OpenAI 兼容流式接口，会返回固定的中文推理过程和回答；它只监听 `127.0.0.1:9000`，不会调用任何真实模型，也不会产生费用。

V3 默认要求用户自带 Key。演示有两种接法：

1. 登录后打开「设置 → AI 接入」，填写任意非空 Key（例如 `mock-demo-key`），接口地址填 `http://127.0.0.1:9000/v1`，日常模型填 `mock-chat`，推理模型填 `mock-reasoner`；
2. 或在后端设置 `ALLOW_SERVER_KEY_FALLBACK=true`，让 mock 作为服务端兜底。

## 演示内容

- 推理模式：流式推理内容 + 进度条 + 折叠/展开
- 文件上传：`sample-brief.txt` 会作为附件上下文
- 官方对话导入：`sample-import.json` 会重建 1 个会话、4 条消息
- 多端布局与下载面板

## 手工启动

### 1. 启动 mock 模型

```bash
python demo/mock_deepseek.py
```

### 2. 启动后端（使用 mock 模型）

先在项目根目录准备好 PostgreSQL（可直接用 `docker compose up -d db redis`），再进入 `backend/` 执行：

```bash
cd backend
export DATABASE_URL="postgresql://chatbot:change-me-strong@127.0.0.1:5432/chatbot"
export ADMIN_PASSWORD="Demo-Admin-2026"
export SECRET_KEY="demo-secret-key"
export DEEPSEEK_API_KEY="mock-demo-key"
export DEEPSEEK_BASE_URL="http://127.0.0.1:9000/v1"
export DEEPSEEK_MODEL="mock-chat"
export DEEPSEEK_REASONER_MODEL="mock-reasoner"
export ASR_ENGINE="disabled"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Windows PowerShell 对应写法：

```powershell
$env:DATABASE_URL="postgresql://chatbot:change-me-strong@127.0.0.1:5432/chatbot"
$env:ADMIN_PASSWORD="Demo-Admin-2026"
$env:SECRET_KEY="demo-secret-key"
$env:DEEPSEEK_API_KEY="mock-demo-key"
$env:DEEPSEEK_BASE_URL="http://127.0.0.1:9000/v1"
$env:DEEPSEEK_MODEL="mock-chat"
$env:DEEPSEEK_REASONER_MODEL="mock-reasoner"
$env:ASR_ENGINE="disabled"
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev
```

打开 <http://127.0.0.1:5173>，使用：

- 用户名：`admin`
- 密码：`Demo-Admin-2026`

## 演示截图

`docs/demo/dreikanterbot-demo.gif` 是自动截取的 12 步演示；原始截图在 `docs/demo/screens/`。

这些素材和 mock 服务只用于展示，不建议部署到生产环境。
