"""Dreikanterbot 演示用本地模型。

它实现了 DeepSeek / OpenAI 兼容的最小流式接口，只用于 UI 演示，
不会调用任何真实模型，也不会产生费用。

启动：
    python demo/mock_deepseek.py
然后让后端使用：
    DEEPSEEK_BASE_URL=http://127.0.0.1:9000/v1
    DEEPSEEK_API_KEY=mock-demo-key
    DEEPSEEK_MODEL=mock-chat
    DEEPSEEK_REASONER_MODEL=mock-reasoner

注意：这个服务只监听本机，不要暴露到公网。
"""
from __future__ import annotations

import asyncio
import json
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="Dreikanterbot demo model")

REASONING = [
    "先拆解一下用户真正想看的东西：不是一段普通回复，而是 Dreikanterbot 的完整工作流。\n",
    "所以要覆盖三个状态：等待输入、推理进行中、回答完成。\n",
    "推理内容必须持续可见，让用户知道模型在做什么，而不是只看到一个转圈。\n",
    "文件入口要一眼能找到，上传后要显示文件名和解析状态。\n",
    "最后用一段结构化的回答收尾，并把「当前是演示模式」说清楚。\n",
]

DEMO_ANSWER = """这是 **Dreikanterbot** 的本地演示回答。

### 你刚刚看到的三个能力

1. **推理模式**：先流式展示推理过程，完成后再给出答案，推理面板可以折叠。
2. **自己的 Key**：V3 默认 BYOK，每个用户在「设置 → AI 接入」填写自己的 Key，平台不代收模型费用。
3. **工作台**：记忆库保存原文件和全文，插件提供可复用的提示词模板；手机、平板、桌面共用同一套界面。

### 当前状态

> 这次演示使用本地 mock 流式模型，不调用真实 DeepSeek API，也不会产生费用。
>
> 真实部署时，在「设置 → AI 接入」填写你的 DeepSeek Key，即可切换为官方 `deepseek-chat` / `deepseek-reasoner`。

如果你想继续体验，可以试试左侧的「继续 DeepSeek 对话」或「下载与设备」。"""

ATTACHMENT_ANSWER = """已收到附件，并把它作为本轮上下文的一部分。

### 演示要点

- 文件上传后会先做文本提取，再随消息一起发给模型。
- 这条回复来自本地 mock 模型，用来演示「文件 + 对话」的完整链路。
- 真实部署时，在「设置 → AI 接入」填写自己的 Key 即可；不需要改服务端环境变量。

> 当前为演示模式，不会调用真实模型。"""


def _chunks(text: str, size: int = 12) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)]


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "mode": "demo"}


@app.get("/v1/models")
async def models() -> dict:
    return {
        "object": "list",
        "data": [
            {"id": "mock-chat", "object": "model", "owned_by": "dreikanterbot-demo"},
            {"id": "mock-reasoner", "object": "model", "owned_by": "dreikanterbot-demo"},
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> StreamingResponse:
    body = await request.json()
    model = str(body.get("model") or "mock-chat")
    messages = body.get("messages") or []
    last_user = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            last_user = str(message.get("content") or "")
            break

    reasoner = "reasoner" in model or bool(body.get("reasoning"))
    has_attachment = "[附件：" in last_user
    answer = ATTACHMENT_ANSWER if has_attachment else DEMO_ANSWER
    completion_id = f"chatcmpl-demo-{uuid4().hex[:12]}"
    created = int(time.time())

    # V3 的「测试连接」使用非流式最小请求；这里也必须返回标准 JSON，
    # 不能把 SSE 当作 chat.completion 返回，否则 OpenAI SDK 解析失败。
    if not body.get("stream"):
        message = {
            "role": "assistant",
            "content": answer,
        }
        if reasoner:
            message["reasoning_content"] = "".join(REASONING)
        return JSONResponse(
            {
                "id": completion_id,
                "object": "chat.completion",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": max(1, len(last_user) // 4),
                    "completion_tokens": max(1, len(answer) // 2),
                    "total_tokens": max(1, len(last_user) // 4 + len(answer) // 2),
                },
            }
        )

    async def event_stream():
        def chunk(delta: dict, finish_reason: str | None = None) -> str:
            return _sse(
                {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": delta,
                            "finish_reason": finish_reason,
                        }
                    ],
                }
            )

        yield chunk({"role": "assistant", "content": ""})

        reasoning_chars = 0
        if reasoner:
            for paragraph in REASONING:
                for piece in _chunks(paragraph, 8):
                    if await request.is_disconnected():
                        return
                    reasoning_chars += len(piece)
                    yield chunk({"reasoning_content": piece})
                    await asyncio.sleep(0.045)

        content_chars = 0
        for piece in _chunks(answer, 10):
            if await request.is_disconnected():
                return
            content_chars += len(piece)
            yield chunk({"content": piece})
            await asyncio.sleep(0.035)

        yield chunk({}, "stop")
        yield _sse(
            {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [],
                "usage": {
                    "prompt_tokens": max(1, len(last_user) // 4),
                    "completion_tokens": max(1, (reasoning_chars + content_chars) // 2),
                    "total_tokens": max(1, len(last_user) // 4 + (reasoning_chars + content_chars) // 2),
                    "completion_tokens_details": {"reasoning_tokens": reasoning_chars // 2},
                },
            }
        )
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=9000, log_level="info")
