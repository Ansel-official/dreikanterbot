# Dreikanterbot Windows 客户端

一个 WebView2 外壳，不复制后端逻辑：

- 首次启动填写服务器地址（例如 `https://chat.example.com`）；
- 之后直接进入你的 Dreikanterbot 工作台；
- 菜单「文件 → 更换服务器地址」可重置；
- 配置保存在 EXE 同目录的 `desktop.config`，WebView2 数据在 `WebView2Data/`；
- 模型 Key、对话、记忆库都在服务器上，不在客户端。

## 构建

要求：

- Windows 10/11
- .NET Framework 4.x（系统自带 `csc.exe`）
- WebView2 Runtime（Win10/11 通常已预装）
- WebView2 SDK NuGet（脚本会自动下载到 `E:\toolchain\webview2`，或用 `-SdkDir` 指定）

```powershell
powershell -ExecutionPolicy Bypass -File desktop\build.ps1
```

产物：`desktop/webview2/release/Dreikanterbot-3.0.0-win-x64.zip`。

> 这是便携客户端，不是把 Python 后端打包进 EXE。服务端仍需按根目录 README 部署。
> 如果要做完全离线的一体机，需要额外的 Python 运行时打包与数据库，当前版本没有做。
