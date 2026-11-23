# TLS 证书目录

生产环境使用 Cloudflare **Full (strict)** 时，需要把 Cloudflare Origin Certificate 放在这里：

```
certs/origin.pem   # 证书（含中间证书链）
certs/origin.key   # 私钥
```

生成方式：Cloudflare 控制台 → `SSL/TLS` → `Origin Server` → `Create Certificate`，
Hostnames 填你的域名（如 `chat.example.com`），Key Format 选 PEM。

放好后执行：

```bash
./deploy.sh
# 或手动：
docker compose -f docker-compose.yml -f docker-compose.https.yml up -d
```

容器内 Nginx 会在 443 端口终止 TLS；80 端口保留用于健康检查与边缘探活。
**绝对不要**把私钥提交到 Git（`.gitignore` 已忽略 `certs/*.pem` 与 `certs/*.key`）。

本地没有证书时，`docker compose up -d` 只启动 HTTP 版本；Cloudflare 若使用
Full (strict) 会报 526，请先按上述步骤配置证书，或把 Cloudflare SSL 模式临时改为 Full
（不推荐长期使用）。
