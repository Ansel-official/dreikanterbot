# 客户端下载

这些文件随仓库提供，也会由 Release 工作流附加到 GitHub Release，并同步到 Gitee Release。

| 文件 | 平台 | 说明 |
|---|---|---|
| `Dreikanterbot-3.3.0-win-x64.zip` | Windows 10/11 x64 | 解压后双击 `Dreikanterbot.exe`；首次填写服务器地址。需要 WebView2 Runtime（Win10/11 通常已装） |
| `Dreikanterbot-3.3.0.apk` | Android 7+ | 侧载安装；首次填写服务器地址。测试签名，正式上架请换自己的 keystore |

## 安装前

客户端只是工作台外壳，必须先部署 Dreikanterbot 服务端（见根目录 README）。服务器地址示例：

- 生产：`https://chat.example.com`
- 局域网调试：`http://192.168.1.20:5173`（手机与电脑同一局域网，Vite 以 `--host 0.0.0.0` 启动）

## 校验

```bash
sha256sum Dreikanterbot-3.3.0-win-x64.zip Dreikanterbot-3.3.0.apk
```

见 [SHA256SUMS](SHA256SUMS)。
