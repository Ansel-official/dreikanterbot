# 设备适配与下载指南

Dreikanterbot 是 **PWA + 响应式 Web**：不需要应用商店，iPhone、iPad、Android、Windows、macOS、Linux 共用同一套界面与服务端历史。

## 直接下载包体

每次发布 `v*` 标签时，GitHub Actions 会自动构建并上传到 Releases：

| 包体 | 文件名 | 用途 |
|---|---|---|
| Web 前端包 | `dreikanterbot-web-<版本>.zip` | 已构建的 `dist/`，部署到与 `/api`、`/ws` 同源的 HTTPS 静态站点 |
| 完整部署包 | `dreikanterbot-deploy-<版本>.zip` | 源码 + Docker Compose + Nginx/Cloudflare 文档，适合部署服务器 |

下载地址：<https://github.com/Ansel-official/dreikanterbot/releases>

> PWA 本身已经是可安装的“应用包”。iPhone/iPad 用 Safari 添加到主屏幕，Android 用 Chrome 安装，桌面用 Chrome/Edge 安装，即可获得独立图标和全屏窗口。

## 推荐设备

| 设备 | 推荐配置 | 浏览器 | 安装方式 |
|---|---|---|---|
| iPhone | iPhone 12 及以上，iOS 16.4+ | Safari 17+ | 分享 → 添加到主屏幕 |
| iPad | iPadOS 16.4+ | Safari 17+ | 分享 → 添加到主屏幕；横屏更佳 |
| Android 手机/平板 | 4GB RAM 及以上，Android 10+ | Chrome 120+ / Edge | 浏览器菜单 → 安装应用/添加到主屏幕 |
| Windows | 8GB RAM 及以上，Win10/11 | Edge 120+ / Chrome 120+ | 地址栏安装图标 |
| macOS | Apple Silicon 或 Intel，macOS 13+ | Safari 17+ / Chrome | Safari 文件 → 添加到程序坞，或 Chrome 安装 |
| Linux | 4GB RAM 及以上 | Chrome/Chromium 120+ | 地址栏安装图标 |
| 服务端（不含语音） | 2 vCPU / 4GB RAM / 20GB 磁盘 | — | Docker Compose |
| 服务端（含本地 Whisper base） | 4 vCPU / 8GB RAM / 30GB 磁盘 | — | Docker Compose，首次启动下载模型 |

### 网络与权限

- **必须 HTTPS**：PWA 安装、麦克风录音、Service Worker 都要求安全上下文（`localhost` 除外）。
- 带宽建议 ≥ 2 Mbps；WebSocket 需要允许 `Upgrade`。
- 手机端首次使用麦克风时，需在浏览器弹窗中允许权限；iOS 还需在系统设置中允许 Safari 麦克风。
- 企业网络若拦截 WebSocket，可让运维放行 `/ws/` 路径；HTTP 轮询只用于流式兜底，不替代实时连接。

## 能力边界

- 聊天主模型为 DeepSeek V4（`deepseek-flash` / `deepseek-v4-pro`）与 Kimi（`kimi-k2.6` / `kimi-k3` 等）。没有网络或未配置对应 Provider 的 Key 时无法生成回复。
- 文件导入支持 PDF、DOCX、PPTX、XLSX、CSV、文本、代码与 ZIP 内文本；图片会保留文件信息，但当前文本模型不做视觉识别，也不在服务器上做 OCR。
- DeepSeek 官方对话导入支持常见 JSON 导出结构；如果官方导出格式发生变化，可在 `backend/app/services/conversation_import.py` 中扩展解析规则。
- V3 提供 Windows WebView2 EXE 与 Android APK 客户端；它们只是工作台外壳，需要先部署服务器。APK 使用测试签名，正式上架请换自己的 keystore；iOS 仍建议使用 PWA。
