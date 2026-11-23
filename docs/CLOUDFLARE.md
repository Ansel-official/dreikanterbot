# Dreikanterbot：Cloudflare 生产配置指南

> 适用站点：`chat.example.com`；源站占位：`203.0.113.10`（TEST-NET-3，**不是真实 IP**）
> 架构：React 18 PWA（Nginx） + FastAPI；Nginx 提供 `/manifest.webmanifest`、`/sw.js`、`/assets/*`，并把 `/api/`、`/ws/`、`/docs`、`/openapi.json`、`/redoc` 反代到 `backend:8000`
> 本文是配置与验证手册，不表示任何配置已经执行。最后更新：2026-11-23
> 控制台导航在 2025 年后有调整；若菜单名不同，以 `Security`、`SSL/TLS`、`Caching`、`Rules`、`Network` 下的实际页面为准。表达式均可直接粘贴到规则编辑器。

## 目录

- [0. 边界、占位符与实施顺序](#0-边界占位符与实施顺序)
- [1. 前置准备与 DNS](#1-前置准备与-dns)
- [2. SSL/TLS](#2-ssltls)
- [3. WAF 自定义规则](#3-waf-自定义规则)
- [4. Rate Limiting 规则](#4-rate-limiting-规则)
- [5. Bot 管理](#5-bot-管理)
- [6. DDoS 防护](#6-ddos-防护)
- [7. 缓存规则](#7-缓存规则)
- [8. 安全响应头与 Transform Rules](#8-安全响应头与-transform-rules)
- [9. WebSocket 注意事项](#9-websocket-注意事项)
- [10. 上传限制](#10-上传限制)
- [11. 可选：Turnstile 保护登录](#11-可选turnstile-保护登录)
- [12. 验证清单与故障排查](#12-验证清单与故障排查)
- [13. 速查表与变更记录模板](#13-速查表与变更记录模板)

## 0. 边界、占位符与实施顺序

### 0.1 流量路径

```text
浏览器/PWA ──HTTPS/WSS──> Cloudflare 边缘 ──HTTPS 443（Full strict）──> Nginx
                                                                        ├─ /、/assets/*、/sw.js、/manifest.webmanifest → 静态文件 + SPA 回退
                                                                        └─ /api/*、/ws/*、/docs、/openapi.json、/redoc → FastAPI:8000
```

Cloudflare 是第二道防线：JWT 校验、管理员权限、ASR 文件校验、WebSocket 鉴权、Redis 业务配额仍必须在 Nginx/FastAPI 完成；源站也不能假设流量一定来自 Cloudflare。

### 0.2 占位符

- `chat.example.com`：对外域名，部署时全局替换。
- `203.0.113.10`：源站 IPv4，文档保留地址，必须替换后再配防火墙。
- `203.0.113.0/24`：办公出口，换成真实 NAT/VPN CIDR。
- `2001:db8::10`、`$TOKEN`：IPv6 占位与测试用 JWT，仅按需使用。

### 0.3 实施顺序

1. 源站 Nginx 跑通 443、静态站、`/api/` 反代、`/ws/` 升级。
2. Cloudflare 添加站点，DNS 橙色云；签发 Origin CA，切 Full (strict)。
3. 打开 Always Use HTTPS、TLS 1.2/1.3，HSTS 按 2.5 决策。
4. 先加 Bypass 缓存，再加 `/assets/*` 缓存，随后加 WAF/限速。
5. 锁定源站防火墙（只放行 Cloudflare，保留办公 SSH），按第 12 节验证。

原则：HSTS/CSP 只在一层设置；动态内容显式 Bypass；边缘限速不是精确配额，账号级额度放 Redis。

## 1. 前置准备与 DNS

### 1.1 接入

1. 控制台 `Add a site` 输入 `example.com`（不是子域），选择套餐。
2. 到注册商把 NS 改为 Cloudflare 分配的两个名称服务器，等待 zone `Active`。
3. 可选：稳定后开启 DNSSEC；改 NS 期间不要同时动 DNSSEC。

### 1.2 DNS 记录

路径：`DNS` → `Records` → `Add record`。

| Type | Name | Content | Proxy status | TTL |
|---|---|---|---|---|
| A | `chat` | `203.0.113.10` | **Proxied（橙色云）** | Auto（灰显 300s） |
| AAAA | `chat` | `2001:db8::10` | **Proxied** | 仅源站有真实 IPv6 时添加 |
| CNAME | `www` | `chat.example.com` | Proxied（可选） | Auto |

- **必须橙色云**：灰色云（DNS only）会暴露源站 IP，WAF/限速/缓存全部失效。
- Proxied 的 TTL 由 Cloudflare 管理（通常 300 秒），不要改成 60 秒。
- 不要建 `origin.`、`direct.`、`dev.` 等指向同一源站的灰色记录。
- 没有 IPv6 就不要加 AAAA；否则部分客户端优先走 IPv6 会超时。
- SPA 的 `/sessions/...`、`/chat/...` 由 Nginx 回退 `index.html`，DNS 不需要单独记录。

### 1.3 只暴露 80/443

| 端口 | 来源 | 用途 |
|---|---|---|
| 80/tcp | Cloudflare IPv4/IPv6 网段 | HTTP→HTTPS、ACME HTTP-01（若用） |
| 443/tcp | Cloudflare IPv4/IPv6 网段 | 业务 HTTPS/WSS |
| 22/tcp | 办公出口/VPN | SSH，禁止对公网开放 |
| 8000/tcp | 仅本机/Docker 内网 | FastAPI |
| 5432/6379 | 仅内网 | DB/Redis |

Cloudflare 网段必须实时拉取，不要长期用文档快照：

- IPv4：<https://www.cloudflare.com/ips-v4/>
- IPv6：<https://www.cloudflare.com/ips-v6/>
- JSON API：`https://api.cloudflare.com/client/v4/ips`

UFW 示例（需 curl/jq；先保留一个已登录 SSH 会话）：

```bash
OFFICE_CIDR="198.51.100.0/24"
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow from "$OFFICE_CIDR" to any port 22 proto tcp
curl -fsS https://api.cloudflare.com/client/v4/ips \
  | jq -r '.result.ipv4_cidrs[], .result.ipv6_cidrs[]' \
  | while read -r cidr; do
      sudo ufw allow from "$cidr" to any port 80 proto tcp
      sudo ufw allow from "$cidr" to any port 443 proto tcp
    done
sudo ufw status numbered   # 核对后再 enable
sudo ufw enable
```

Cloudflare 网段会变；用 systemd timer 每周刷新 nftables set，或定期清理 UFW 旧规则。云厂商安全组也要做同样的入站限制。

### 1.4 避免源站 IP 泄露

- 不建灰色云记录、清理历史 A 记录；优先 **Cloudflare Origin CA**（不被浏览器信任，不会把内部主机名写进公共 CT 日志）。
- 用 SecurityTrails、Censys、Shodan、crt.sh 搜索域名和 `203.0.113.10`，确认没有历史泄露。
- 已泄露：换 IP 最省事；否则用 Cloudflare Tunnel（出站连接，源站不开放入站）或严格防火墙。
- 检查 FastAPI `servers`/`root_path`、错误页、sourcemap、邮件头，避免内部地址泄露；Docker 端口写 `127.0.0.1:8000:8000`。

## 2. SSL/TLS

### 2.1 Full (strict)

路径：`SSL/TLS` → `Overview` → `SSL/TLS encryption mode`。选择 **Full (strict)**：Cloudflare 到源站走 HTTPS，并校验证书由受信任 CA（含 Origin CA）签发、主机名匹配、未过期。

- 不用 `Flexible`：回源明文，容易重定向循环。
- 不用 `Full`：只加密不校验证书，失去回源身份校验。
- 证书无效/过期/主机名不符会报 **526**，不是 502。

### 2.2 Origin CA（推荐）

路径：`SSL/TLS` → `Origin Server` → `Origin Certificates` → `Create Certificate`。

1. `Generate private key and CSR with Cloudflare`；RSA 2048 或 ECC P-256。
2. Hostnames 填 `chat.example.com`；非必要不加 `*.example.com`。
3. 有效期选控制台允许的较长时间；Cloudflare **不发到期通知**，自行登记。
4. Key Format 选 PEM；私钥只显示一次：

```text
/etc/nginx/certs/chat.example.com.pem   # 证书
/etc/nginx/certs/chat.example.com.key   # 私钥，chmod 600
```

```nginx
server {
    listen 443 ssl;
    http2 on;                 # Nginx < 1.25.1 用 listen 443 ssl http2;
    server_name chat.example.com;
    ssl_certificate     /etc/nginx/certs/chat.example.com.pem;
    ssl_certificate_key /etc/nginx/certs/chat.example.com.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
}
```

Origin CA 的链由 Cloudflare 信任，通常只装 leaf；若 OpenSSL 报链不完整，再拼接 Cloudflare Origin CA 根证书。不要用自签证书，Full (strict) 会 526。

> **本仓库已内置 HTTPS 覆盖**：把证书保存为 `certs/origin.pem` 与 `certs/origin.key`，
> `deploy.sh` 会自动叠加 `docker-compose.https.yml`，容器内 Nginx 监听 443。
> 若沿用本文的 `/etc/nginx/certs/chat.example.com.*` 命名，请相应修改 `docker-compose.https.yml`
> 的挂载路径与 `frontend/nginx/nginx-ssl.conf` 中的证书路径。

### 2.3 Let's Encrypt（替代方案）

源站只放行 Cloudflare 时，HTTP-01 验证服务器连不进来，优先 **DNS-01**：

```bash
sudo certbot certonly --dns-cloudflare \
  --dns-cloudflare-credentials /etc/letsencrypt/cloudflare.ini \
  -d chat.example.com
sudo certbot renew --deploy-hook "systemctl reload nginx"
```

若坚持 HTTP-01，必须临时放行 Let's Encrypt 网段或开放 80；不推荐。续期失败会导致 Full (strict) 回源报 525/526，必须监控到期时间。

### 2.4 边缘 TLS 开关

路径：`SSL/TLS` → `Edge Certificates`。

| 设置 | 值 | 说明 |
|---|---|---|
| Always Use HTTPS | **On** | HTTP 301 到 HTTPS |
| Automatic HTTPS Rewrites | **On** | 改写页面内 http 资源，减少混合内容 |
| Minimum TLS Version | **TLS 1.2** | 禁用 1.0/1.1 |
| TLS 1.3 | **On** | 源站 Nginx 也开 |
| HSTS | 见 2.5 | 不要与 Nginx 重复 |
| No-Sniff Header | 按需 | Nginx 已发就保持 Off |

### 2.5 HSTS：只在一层设置

```text
Strict-Transport-Security: max-age=15552000
```

- `max-age=15552000`（180 天）作为第一阶段；控制台可选 1–12 个月。
- `includeSubDomains` 第一阶段关：确认 `example.com` 下所有子域都能 HTTPS 再开。
- `preload` 不要急着开：进入浏览器预加载列表后撤销需数月；申请通常要求 12 个月 + `includeSubDomains`，内部系统不建议。
- HSTS 是粘性的：开启后暂停 Cloudflare、改灰色云、证书过期或关闭 HTTPS，用户在 max-age 内会无法访问。

**二选一**：A）Cloudflare `Edge Certificates` → HSTS 开，Max Age 6 个月，`includeSubDomains`/`Preload` 关，同时删除 Nginx 的 HSTS 头；B）保留 Nginx HSTS，Cloudflare HSTS 保持 **Off**。不要两层都开，否则出现两个 HSTS 头。验证：`curl -sI https://chat.example.com | grep -ci '^strict-transport-security:'` 应为 1。

## 3. WAF 自定义规则

### 3.1 入口与限制

路径：`Security` → `WAF` → `Custom rules`（新版可能为 `Security` → `Security rules` → `Custom rules`）。

执行顺序：HTTP DDoS → **Custom rules** → Rate limiting → Managed rules。自定义规则里的 Block 会终止后续评估，所以 Skip 规则必须放最前。免费版最多 **5 条**、无 `Log` 动作（企业版才有）；Pro 20 条、Business 100 条。本文不使用正则 `matches`，只用 `eq`/`in`/`starts_with`/`contains`/`lower()`。

### 3.2 七条规则（按从上到下创建）

**W0 健康检查放行（Skip，必须最前）**

动作：`Skip`；勾选跳过 Super Bot Fight Mode、Managed Rules 等（以控制台为准）。

```text
http.host eq "chat.example.com" and http.request.uri.path eq "/healthz"
```

`/healthz` 建议由 Nginx 直接返回 200。该规则只处理自定义/托管/Bot 层；健康检查频率低，通常不会触发限速。Bot Fight Mode 不能用 Skip 放行（见第 5 节）。

**W1 恶意 User-Agent / 扫描器 / 敏感路径**

动作：`Block`。

```text
http.host eq "chat.example.com" and (lower(http.user_agent) contains "sqlmap" or lower(http.user_agent) contains "nikto" or lower(http.user_agent) contains "nmap" or lower(http.user_agent) contains "masscan" or lower(http.user_agent) contains "acunetix" or lower(http.user_agent) contains "nessus" or lower(http.user_agent) contains "dirbuster" or lower(http.user_agent) contains "gobuster" or lower(http.user_agent) contains "zgrab" or http.request.uri.path eq "/.env" or starts_with(http.request.uri.path, "/.git/") or http.request.uri.path eq "/server-status" or starts_with(http.request.uri.path, "/actuator/"))
```

不要拦 `curl`、`python-requests`、`wget`，它们可能是监控/CI。空 UA 可另用 `Managed Challenge` 观察。不要误伤 `/.well-known/acme-challenge/`；若用 HTTP-01，需在其前面加放行规则。

**W2 登录入口方法锁定**

动作：`Block`。

```text
http.host eq "chat.example.com" and http.request.uri.path eq "/api/auth/login" and http.request.method ne "POST"
```

`POST /api/auth/login` 是唯一合法入口。**5 次/分钟/IP 的计数不在这里做**（自定义规则没有计数能力），见 4.2；若观察到撞库，再叠加 `cf.threat_score ge 40`，但该字段有误伤，先观察。

**W3 管理后台仅允许办公出口**

动作：`Block`。

```text
http.host eq "chat.example.com" and starts_with(http.request.uri.path, "/api/admin/") and not ip.src in {203.0.113.0/24}
```

把 CIDR 换成真实办公出口/VPN；有 IPv6 时补集合。更推荐在 `Security` → `Lists` 建 `office_egress`，表达式用 `not ip.src in $office_egress`，换 IP 不改规则。

**W4 异常国家/地区（可选）**

动作：优先 `Managed Challenge`（HTML），API 路径用 `Block`。

```text
http.host eq "chat.example.com" and not ip.geoip.country in {"CN" "HK" "SG"}
```

`ip.geoip.country` 是 ISO 两位代码。先观察一周，确认海外同事/跨境 VPN 不误伤；不要上线即全球 Block。

**W5 非预期 HTTP 方法**

动作：`Block`。

```text
http.host eq "chat.example.com" and not http.request.method in {"GET" "HEAD" "POST" "PUT" "PATCH" "DELETE" "OPTIONS"}
```

WebSocket 握手是 GET，不会被误伤；CORS 预检是 OPTIONS，保留。

**W6 保护 API 文档**

动作：`Block`。

```text
http.host eq "chat.example.com" and (http.request.uri.path in {"/docs" "/openapi.json" "/redoc"} or starts_with(http.request.uri.path, "/docs/") or starts_with(http.request.uri.path, "/redoc/")) and not ip.src in {203.0.113.0/24}
```

`/openapi.json` 会暴露全部接口和内部模型。推荐 IP 白名单（本规则）；也可在 Nginx 加 `auth_basic`，或用 Cloudflare Access。Cloudflare Transform Rules 不能直接生成 Basic Auth。

### 3.3 免费版 5 条压缩

W0–W6 共 7 条，Free 只能 5 条：保留 W0、W2、W3、W6；把 W1+W5 合成一条 Block；W4 暂不建，升级 Pro 再加。合并后在表达式编辑器点 “Format” 检查括号。

### 3.4 托管规则

路径：`Security` → `WAF` → `Managed rules`。

| 套餐 | 可部署 | 建议 |
|---|---|---|
| Free | Free Managed Ruleset | 开启，规则少、误伤低 |
| Pro/Business | Cloudflare Managed、OWASP Core | 先只开 Cloudflare Managed；OWASP 对 JSON/ multipart 易误报，观察后再开 |

WAF 对请求体检查有限：Free 1 MB，其他套餐默认更低。`POST /api/asr` 的音频 body 不会被完整检查，**不要指望 WAF 扫描音频**；文件类型、magic bytes、时长、大小必须在 FastAPI 校验。OWASP 若误报，用 WAF 例外只跳过 `/api/asr`，不要关整站。

## 4. Rate Limiting 规则

### 4.1 套餐差异

路径：`Security` → `WAF` → `Rate limiting rules`。

| 能力 | Free | Pro | Business |
|---|---|---|---|
| 规则数 | 1 | 2 | 5 |
| 计数窗口 | 10 秒 | 最长 1 分钟 | 最长 10 分钟 |
| 缓解时长 | 10 秒 | 最长 1 小时 | 最长 1 天 |
| 表达式字段 | Path、Verified Bot | Host/URI/Path/Full URI/Query、Verified Bot | 再加 Method、Source IP、User Agent |
| 计数特征 | IP | IP | IP、IP with NAT support |

“登录 5 次/分钟”在 Free 做不到（只有 10 秒窗口、1 条规则）；生产建议至少 Pro，要同时覆盖登录/ASR/WS 握手则需 Business。

### 4.2 目标限速表（Business）

| 优先级 | 路径 | 阈值 | 窗口 | 动作 | 缓解 | 说明 |
|---|---|---|---|---|---|---|
| P0 | `/api/auth/login` | 5 次 | 60 秒 | Block | 300 秒 | 仅 POST 入口，IP 计数 |
| P0 | `/api/asr` | 10 次 | 60 秒 | Block | 300 秒 | 音频成本高 |
| P1 | `/ws/chat` | 30 次 | 60 秒 | Block | 60 秒 | 只限握手，不限已建立帧 |
| P1 | `/api/admin/*` | 20 次 | 60 秒 | Block | 300 秒 | 与 W3 叠加 |
| P2 | `/api/sessions/*` | 120 次 | 60 秒 | Block | 60 秒 | 防遍历 |
| P2 | `/api/*` | 300 次 | 60 秒 | Block | 60 秒 | 按实际轮询量调 |

- 表达式示例：`http.request.uri.path eq "/api/auth/login"`；`starts_with(http.request.uri.path, "/api/admin/")`。
- Pro 表达式不含 Method，登录规则只写路径即可（登录仅 POST）；Business 可加 `and http.request.method eq "POST"`。
- 动作用 `Block`：API 客户端不会解 Managed Challenge；命中通常返回 **429**（1015 页面），自定义规则 Block 是 **403**。
- 计数按数据中心，不是全球精确；有秒级延迟，超额请求可能仍到源站。后端仍需登录失败锁定。

### 4.3 Pro 的取舍

Pro 仅 2 条：登录 + ASR。WS 握手限速放 Nginx，以 `CF-Connecting-IP` 为 key：

```nginx
# http {} 块
limit_req_zone $http_cf_connecting_ip zone=ws_handshake:10m rate=30r/m;
# location /ws/ 内
limit_req zone=ws_handshake burst=10 nodelay;
```

前提：源站只放行 Cloudflare，`CF-Connecting-IP` 才可信；否则头可伪造，限速失效。

### 4.4 Free 单条规则

只保护登录：`2 次 / 10 秒`，Block 10 秒（约 12 次/分钟）。比 `1 次/10 秒` 更不容易误伤连续输错的用户；慢速撞库靠 FastAPI 的“登录 IP 60 次 / 5 分钟 + 同账号 10 次 / 5 分钟”限速兜底。

### 4.5 与 Redis 每日配额互补

| 层 | 维度 | 作用 |
|---|---|---|
| Cloudflare | IP、路径、分钟级 | 防匿名刷、保护源站/ASR 成本 |
| Nginx | IP、路径、秒级 | 补 WS 握手等边缘规则覆盖不到的路径 |
| FastAPI + Redis | 用户/租户、天/小时 | 精确业务配额、公平性、可审计 |

Redis 示例：`quota:{YYYY-MM-DD}:{user_id}`，`INCR` 后首次设 `EXPIRE` 到次日 00:00（Asia/Shanghai），超过每日额度返回 429；管理员与访客的日志写入 `usage_logs` 供审计。边缘不知道 JWT 用户，Redis 挡不住未登录 IP 洪水，两者必须叠加。

## 5. Bot 管理

路径：`Security` → `Settings` → 筛选 `Bot traffic`。

### 5.1 Bot Fight Mode 的副作用

- **不能用 WAF Skip**：BFM 不在 Ruleset Engine 中运行，`Skip`/`Allow` 对它无效；只有 Super Bot Fight Mode 支持 Skip。
- 可能挑战 API 客户端、移动端、监控探针、CI（403/挑战页/超时）；自动启用 JavaScript Detections 注入 `/cdn-cgi/challenge-platform/`，严格 CSP 可能报错；且保护整个域名，不能按路径关闭。

**建议**：Free 套餐且存在监控/CLI 客户端时，优先**关闭 BFM**，用 WAF + 限速 + Turnstile 替代；开启则必须用 curl、移动端、监控探针各验一遍。

### 5.2 健康检查放行

Pro+ 的 SBFM 支持 Skip：规则表达式 `http.host eq "chat.example.com" and (http.request.uri.path eq "/healthz" or http.request.uri.path eq "/api/health")`，动作 `Skip`，勾选跳过 SBFM/Managed Rules（以控制台为准），放最前。Free 的 BFM **没有可靠 Skip**，不要相信“IP Access Rule 能放行”，最稳妥是关闭 BFM。`/healthz` 由 Nginx 直接返回、不查 DB/Redis；`/api/health` 会检查 PostgreSQL/Redis，适合容器编排与内部监控。

### 5.3 Super Bot Fight Mode（Pro+）

路径：`Security` → `Settings` → `Bot traffic` → `Super Bot fight mode`。

初始建议：Definitely automated = Block；Likely automated = Managed Challenge；Verified bots = Allow；Static resource protection 先 Off（避免 PWA 首屏被挑战）；JavaScript detections 按 CSP 能力决定。SBFM 自定义例外用 `Skip`，自定义规则先于 SBFM 执行。若用 Cloudflare Tunnel，官方提示 `Definitely Automated` 设 Allow，否则可能 `websocket: bad handshake`。

## 6. DDoS 防护

- **L3/4 与 L7**：L3/4 自动防护、始终开启，普通套餐无需细调；L7 的 `HTTP DDoS Attack Protection` 托管规则集始终启用，只能调动作/灵敏度。入口通常在 `Security` → `DDoS`，新版也可能在 `Security` → `Settings`。
- 非 Enterprise 通常只有 **1 条 override**，不能自定义表达式；Enterprise 才有多条带表达式的覆盖规则。不要平时乱调灵敏度，先看 Security Events。
- WebSocket：所有套餐支持；`Network` → `WebSockets` 保持 On。初始 `101` 按普通 HTTP 请求计数并经过 WAF/限速/DDoS；建立后 WAF 不再检查帧。Cloudflare 重启边缘可能断开 WS，客户端必须自动重连。
- HTTP/2/3：客户端支持；WS 升级本质是 HTTP/1.1 Upgrade 语义，浏览器会回退，通常不需要为 WS 关闭 HTTP/2。只有自定义反代/Tunnel 出现 `bad handshake` 时才临时关闭 HTTP/2 做对照。
- 观察指标：Security Events（DDoS/WAF 命中）、Traffic 的请求/带宽/状态码、源站 5xx/499/502/504、CPU/内存/Redis 延迟、WS 重连率、缓存命中率。**Under Attack Mode** 是最后手段：会挑战包括 API 客户端在内的请求，可能打断 REST/WS；优先用 WAF + 限速 + DDoS override。

## 7. 缓存规则

### 7.1 默认行为

Cloudflare 默认按扩展名缓存部分静态内容（`.js`、`.css`、图片、字体等），HTML/JSON 默认不缓存；源站 `no-store/private/no-cache/max-age=0` 或 `Set-Cookie` 时不缓存；无缓存头的 200 可能按默认 TTL（约 120 分钟）缓存。因此 `/sw.js`（也是 `.js`）若没发 `no-cache`，可能被边缘缓存，PWA 更新卡死。

### 7.2 顺序：最后匹配的规则赢

Cache Rules 可叠加；多条同时匹配时，冲突设置以**最后匹配**的规则为准。控制台越靠下的规则优先级越高。所以顺序是：**先放 Bypass（宽泛），最后放 `/assets/*` 缓存（具体）**。如果把 assets 缓存放最上面，下面一条“非 assets 全部 Bypass”会把 assets 也 bypass。

### 7.3 策略表

| 顺序 | 规则 | 匹配 | Cache eligibility | Edge TTL | Browser TTL |
|---|---|---|---|---|---|
| 1 | `bypass-api-ws-docs` | `/api/*`、`/ws/*`、`/docs*`、`/openapi.json`、`/redoc*` | Bypass | — | — |
| 2 | `bypass-pwa-entry` | `/sw.js`、`/manifest.webmanifest`、`/index.html`、`/` | Bypass | — | — |
| 3 | `bypass-non-assets` | `not starts_with(http.request.uri.path, "/assets/")` | Bypass | — | — |
| 4 | `cache-assets-immutable` | `starts_with(http.request.uri.path, "/assets/")` | Eligible | 1 个月（2592000s） | 1 年（31536000s） |

1–3 动作都是 Bypass，重叠无妨；关键是 4 必须在最后。

### 7.4 完整 Cache Rule 字段

| 字段 | 值 |
|---|---|
| Rule name | `cache-assets-immutable` |
| When incoming requests match | `http.host eq "chat.example.com" and starts_with(http.request.uri.path, "/assets/")` |
| Cache eligibility | `Eligible for cache` |
| Edge TTL | `Ignore cache-control header and use this TTL` → 1 month（2592000 秒） |
| Browser TTL | `Override origin` → 1 year（31536000 秒） |
| Cache Key → Query String | `Ignore query string`（套餐不提供则保持默认） |

- Edge 1 个月、Browser 1 年刻意错开：浏览器按 hash 长期缓存，边缘留短一些便于止血。
- **Ignore query string**：文件名已带构建 hash，查询串通常只是版本/统计参数，忽略可提高命中率；若套餐不支持该选项，保持默认，确认没有 `?v=` 返回不同内容的逻辑。
- **Bypass 只影响边缘，不影响浏览器**；`/sw.js`、`/index.html` 仍需 Nginx 发 `no-cache`。

### 7.5 Nginx 配合

```nginx
location /assets/ { expires 1y; try_files $uri =404; access_log off; }
```

部署后同名文件被覆盖（不推荐）时，purge `/assets/` 前缀并让用户强刷。

### 7.6 PWA 不卡旧版本

1. Nginx 对 `/sw.js`、`/manifest.webmanifest`、`/index.html` 返回 `Cache-Control: no-cache`（本项目使用 `expires -1`）。
2. Cloudflare Cache Rule 对三者 `Bypass cache`；Service Worker 注册用 `navigator.serviceWorker.register('/sw.js', { updateViaCache: 'none' })`。
3. 发布后 purge：

```text
Caching → Configuration → Purge Cache → Purge by URL
https://chat.example.com/
https://chat.example.com/index.html
https://chat.example.com/sw.js
https://chat.example.com/manifest.webmanifest
```

4. 验证 `cf-cache-status` 为 `DYNAMIC`/`BYPASS`，不是 `HIT`。用户仍见旧版：DevTools → Application → Service Workers → Unregister，再硬刷新；检查 `index.html`/`sw.js` 的缓存头。

带 hash 的 `/assets/*` 不需要每次 purge；回滚同名覆盖时才 purge 前缀。不要长期开 Development Mode（3 小时后自动关）。

## 8. 安全响应头与 Transform Rules

Nginx 已设 HSTS/CSP/X-Frame-Options，Cloudflare 只补缺的，或明确一层为唯一来源。路径：`Rules` → `Transform Rules` → `Modify response header`。`Set static/dynamic` 会覆盖同名头；`Add` 会追加，可能重复；`Remove` 删除全部同名头。

| 响应头 | 建议来源 | 说明 |
|---|---|---|
| `Strict-Transport-Security` | Nginx 或 Cloudflare，二选一 | 不要重复 |
| `Content-Security-Policy` | Nginx | 若用 Turnstile，放行 `https://challenges.cloudflare.com` 与 `/cdn-cgi/challenge-platform/` |
| `X-Frame-Options` | Nginx | 与 CSP `frame-ancestors` 一致 |
| `X-Content-Type-Options` | Nginx 或 Cloudflare No-Sniff | 一个即可 |
| `Referrer-Policy` | Nginx/Transform | `strict-origin-when-cross-origin` |

Transform 示例（仅 Nginx 未设置时）：Rule name `set-referrer-policy`，匹配 `http.host eq "chat.example.com"`，Operation `Set static`，Header `Referrer-Policy`，Value `strict-origin-when-cross-origin`。`Set` 会覆盖源站同名头；Nginx 已设就改 Nginx。

明确关闭/不开启：**Email Address Obfuscation**（`Scrape Shield`，会改写 HTML 邮箱，收益低）；**Rocket Loader**（`Speed` → `Optimization`，破坏 React/PWA）；**Auto Minify**（已逐步下线）；**BFM 的 JavaScript Detections**（严格 CSP 易冲突）。

## 9. WebSocket 注意事项

### 9.1 基本链路

`Network` → `WebSockets` 保持 **On**（全套餐支持）。握手：`GET https://chat.example.com/ws/chat?token=<JWT>` + `Upgrade: websocket`。Cloudflare 只把初始 `101` 当一个请求，后续帧不计入 WAF/限速；`/ws/*` 在 Cache Rule 中 Bypass。

### 9.2 20 秒心跳与空闲超时

- 服务端每 20 秒发应用层心跳或 WebSocket Ping，客户端回 Pong/ACK；20 秒远小于常见空闲阈值。
- Cloudflare 官方只说明“双向无数据一段时间会关闭”，Enterprise 可自定义；**没有公开固定秒数**。当前 `Proxy Read Timeout` 为 **125 秒**（等待源站响应，Enterprise 可调），历史常被引用为 100 秒；它针对普通 HTTP，不是已建立的 WebSocket。
- 客户端连续 2 次心跳未收到（约 40–60 秒）就重连，不要等 TCP 超时。

### 9.3 Nginx 放宽超时

Nginx 默认 `proxy_read_timeout 60s` 会切安静连接，表现是 `1006`：

```nginx
location /ws/ {
    proxy_pass http://backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_buffering off;
}
```

前方云 LB 的空闲超时也要大于 60 秒；不要在 WS location 开 `proxy_cache`。

### 9.4 1006 与 100/125 秒误区

`1006` 是客户端“异常关闭”，不是 Cloudflare 错误码。常见原因：Nginx `proxy_read_timeout` 太短、FastAPI 重启、源站 OOM、客户端网络切换、Cloudflare 边缘重启、公司代理空闲切断。`524` 是等源站响应超时，握手阶段可能出现 524/502，而不是 WS 帧的 1006。不要为 WS 盲目关闭 HTTP/2；先查 Nginx error log、FastAPI 日志、Security Events。

### 9.5 连接数、鉴权、重连

- 并发连接资源受套餐/合同限制，公开文档没有通用固定数字；控制单用户连接数更重要：**一个标签页一条连接**，重连用指数退避 + 抖动（1s、2s、4s…上限 30s），服务端限制单用户连接数（如 3 条）。
- JWT 放 query 有泄露风险（Nginx/Cloudflare 日志、浏览器历史、Referer）。生产建议改为短期一次性 WS ticket：先 `POST /api/ws-ticket` 拿 30–60 秒有效 ticket，再 `wss://.../ws/chat?ticket=...`，后端校验后立即作废；暂时保留 `?token=` 时至少把访问日志 query 脱敏。

### 9.6 代理协议与真实 IP

Cloudflare HTTP 代理到源站**不使用 PROXY protocol**；源站看到的对端是 Cloudflare IP。真实客户端 IP 用 `CF-Connecting-IP`：本项目的 Nginx 会把该头透传给 FastAPI，FastAPI 优先读取 `CF-Connecting-IP`/`X-Real-IP`/`X-Forwarded-For`。**因此源站必须只放行 Cloudflare 网段并禁止直连**，否则客户端可以伪造该头绕过 IP 限速。日志记录 `CF-Ray`、`CF-Connecting-IP`、`X-Request-ID`，便于关联 Security Events。

## 10. 上传限制

| 层 | 限制 | 配置 |
|---|---|---|
| Cloudflare | 100 MB（Free/Pro）；200 MB（Business） | 套餐固定；Enterprise 可在 `Network` → `Maximum Upload Size` 调 |
| Nginx | 25 MB | `client_max_body_size 25m;` |
| FastAPI | 20 MB | 校验 `Content-Length` + 流式累计字节，返回 413 |

ASR 20 MB 远低于 100 MB；Nginx 留 multipart 边界余量，不要正好 20m。Cloudflare 100 MB 是**整个请求体**上限，普通套餐没有按路径的请求体限制；用 WAF/限速控频，后端控大小。

FastAPI 本项目已实现：MIME 白名单、流式累计大小上限、临时文件用后删除、上游超时、并发信号量与 Redis 每日配额。进一步加固建议：校验 magic bytes、解析音频时长/采样率、限制单用户 ASR 并发。

## 11. 可选：Turnstile 保护登录

Turnstile 不改变 JWT 流程：登录成功仍返回原 JWT（30 天），只是在 `POST /api/auth/login` 前增加人机校验；不能替代限速、账号锁定和密码策略。

### 11.1 控制台

`Turnstile` → `Add site`；Hostname `chat.example.com`；Widget Mode `Managed`；记录 Site Key（前端）和 Secret Key（后端环境变量）。无特殊需要不要开 Pre-clearance。

### 11.2 前端

```html
<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>
<div class="cf-turnstile" data-sitekey="0x4AAAAAAA..."></div>
```

提交时把隐藏字段 `cf-turnstile-response`（或 `turnstile.getResponse()`）随登录请求发给后端；过期/失败调用 `turnstile.reset()`。

### 11.3 后端校验

```python
async def verify_turnstile(token: str, client_ip: str) -> None:
    if not token:
        raise HTTPException(400, "turnstile token missing")
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": settings.TURNSTILE_SECRET, "response": token, "remoteip": client_ip},
        )
    result = resp.json()
    if not result.get("success"):
        raise HTTPException(403, "turnstile verification failed")
```

- Siteverify：`https://challenges.cloudflare.com/turnstile/v0/siteverify`；中国域名 Widget 用 `https://challenges.cloudflare-cn.com/...`。
- Token 300 秒有效、单次使用；重复提交返回 `timeout-or-duplicate`。
- `remoteip` 用 `CF-Connecting-IP`；本地开发拿不到时退回可信的 `X-Forwarded-For`。失败策略建议 fail closed（403/503 + 告警），保留限速/账号锁定兜底。
- CSP 放行 `script-src`/`frame-src`/`connect-src` 的 `https://challenges.cloudflare.com`；用 nonce 时确认注入脚本不被拦截。

不要只在登录页加 Widget 而不校验后端；不要给 `/api/asr`、`/ws/chat` 加 Turnstile；Secret 不要进前端或仓库；加了 Turnstile 也不要关限速。

## 12. 验证清单与故障排查

### 12.1 源站、DNS、TLS、回源

```bash
sudo nginx -t
DOMAIN=chat.example.com; ORIGIN=203.0.113.10
openssl x509 -in /etc/nginx/certs/chat.example.com.pem -noout -subject -issuer -dates
curl -k -sS -o /dev/null -w "%{http_code}\n" https://127.0.0.1/ -H "Host: chat.example.com"
dig +short "$DOMAIN" A
dig +short "$DOMAIN" AAAA                      # 期望 Cloudflare 地址，不是源站
curl -sI "https://$DOMAIN/" | grep -Ei '^(HTTP/|server:|cf-ray:|strict-transport-security:)'
curl -sI "http://$DOMAIN/" | grep -Ei '^(HTTP/|location:)'
openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" -tls1_1 </dev/null   # 应失败
openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" -tls1_2 </dev/null   # 应成功
curl -k --resolve "$DOMAIN:443:$ORIGIN" "https://$DOMAIN/" --connect-timeout 5      # 期望超时/拒绝
curl -sI "https://$DOMAIN/" | grep -ci '^strict-transport-security:'                # 期望 1
```

### 12.2 缓存

```bash
DOMAIN=chat.example.com
ASSET_URL="https://$DOMAIN/assets/<从 DevTools 复制的真实文件>.js"
for i in 1 2; do curl -sI "$ASSET_URL" | grep -Ei 'cf-cache-status|cache-control|age'; done
curl -sI "https://$DOMAIN/sw.js" | grep -Ei 'cf-cache-status|cache-control'
curl -sI "https://$DOMAIN/" | grep -Ei 'cf-cache-status|cache-control'
curl -sI "https://$DOMAIN/api/health" | grep -Ei 'cf-cache-status|cache-control'
```

第一次可能 MISS，第二次同机房应 HIT（edge 约 1 个月）；`sw.js`/`/`/API 期望 DYNAMIC/BYPASS 且 `no-cache`。

### 12.3 WAF 与限速

```bash
DOMAIN=chat.example.com
curl -s -o /dev/null -w "%{http_code}\n" -A "sqlmap/1.0" "https://$DOMAIN/"          # 403
curl -s -o /dev/null -w "%{http_code}\n" -X TRACE "https://$DOMAIN/"                  # 403
curl -s -o /dev/null -w "%{http_code}\n" "https://$DOMAIN/openapi.json"               # 非办公 403
curl -s -o /dev/null -w "%{http_code}\n" "https://$DOMAIN/api/admin/users"            # 非办公 403
for i in $(seq 1 7); do
  curl -s -o /dev/null -w "%{http_code}\n" -H "Content-Type: application/json" \
    -d '{"username":"__rate_limit_probe__","password":"wrong"}' \
    "https://$DOMAIN/api/auth/login"; sleep 1
done   # 第 6 次左右 429（或 403，取决于动作）
```

先用独立测试出口，避免把办公 NAT 整体锁死。

### 12.4 WebSocket 与 ASR

```bash
DOMAIN=chat.example.com; TOKEN="<登录返回的 JWT>"
npx wscat -c "wss://$DOMAIN/ws/chat?token=$TOKEN"     # 观察 101 和 20 秒心跳
curl -i -N --max-time 3 -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  "https://$DOMAIN/ws/chat?token=$TOKEN"               # 101；curl 超时返回 28 正常
curl -sS -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOKEN" \
  -F "file=@sample.webm;type=audio/webm" "https://$DOMAIN/api/asr"
dd if=/dev/zero of=/tmp/21mb.bin bs=1M count=21
curl -sS -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/21mb.bin;type=audio/webm" "https://$DOMAIN/api/asr"   # 413
```

### 12.5 仪表盘检查

`Security` → `Events` 看 WAF/限速/Bot/DDoS 命中的规则名；`Caching` → `Analytics` 看 `/assets/*` 命中率和 `/api/*` 是否为 0；`Analytics` → `Traffic` 看 4xx/5xx、带宽、国家；`DNS` → `Records` 确认橙色云且无灰色 `origin`；`SSL/TLS` → `Edge Certificates` 确认证书正常、HSTS 只有一层。

### 12.6 常见故障

| 现象 | 常见原因 | 处理 |
|---|---|---|
| **521/522** | 源站拒绝连接或 TCP 超时：Nginx 没起、只监听 127.0.0.1、防火墙没放行 Cloudflare、IP/路由错、源站过载 | `ss -lntp` 看 443；本机 curl；查 UFW/安全组/A 记录；建连约 19 秒、请求确认约 90 秒 |
| **524** | 源站超过 Proxy Read Timeout（当前 125 秒，Enterprise 可调）；ASR/慢查询/锁等待 | 查 Nginx `proxy_read_timeout`、FastAPI 慢日志；优化/异步化；免费版不能调边缘超时 |
| **525/526** | 525 是 TLS 握手失败（协议/cipher）；526 是 Full (strict) 证书无效（自签、过期、主机名不符、链不完整） | 开 TLS 1.2+1.3；换 Origin CA/有效 LE；`openssl x509` 查 SAN/有效期；看 error log |
| **1015/1016** | 1015 被限速；1016 无法解析源站（A 记录缺失/写错、CNAME 目标不存在） | 查 Events 的限速规则；`dig` 源站记录并修 DNS |
| **WS 1006** | Nginx `proxy_read_timeout` 太短、FastAPI 重启、OOM、网络切换、边缘重启 | Nginx 设 3600s；查 error log；指数退避重连；不要归因“100 秒超时” |
| **静态资源旧版** | `sw.js`/`index.html` 被边缘或浏览器缓存；SW 未更新 | 查 `cf-cache-status`/`Cache-Control`；purge 四个入口；注销 SW 再硬刷 |
| **限速误伤办公** | 办公室共享 NAT；登录 5/min 太低 | 看 `CF-Connecting-IP`；提阈值/用 NAT 计数；Business 排除办公 CIDR |
| **Bot 拦截 API** | BFM 不能 Skip；客户端不会解 JS 挑战 | 关闭 BFM；Pro+ 用 SBFM + 健康检查 Skip |
| **413** | 超过 Cloudflare 100MB、Nginx 25m 或 FastAPI 20MB | 看响应体是哪一层；逐层核对限制 |
| **`/docs` 打不开** | W6 挡了办公 IP，或 CSP 挡 Swagger CDN | 确认出口 IP；检查 CSP；必要时 Nginx Basic Auth |
| **API 被缓存** | Cache Rule 顺序反了，或源站发了 public 缓存头 | 记住“最后匹配赢”；assets 规则放最后；API 加 `no-store` |

## 13. 速查表与变更记录模板

### 13.1 Cloudflare 规则速查表

| 项目 | 控制台路径（以当前为准） | 关键值 | 备注 |
|---|---|---|---|
| DNS | `DNS` → `Records` | `chat` A → `203.0.113.10`，Proxied，TTL Auto | 禁止灰色云 |
| 源站防火墙 | 安全组 + UFW | 仅 80/443 放行 Cloudflare；22 放行办公 | 实时拉取网段 |
| 加密模式 | `SSL/TLS` → `Overview` | Full (strict) | 不用 Flexible |
| 强制 HTTPS | `SSL/TLS` → `Edge Certificates` | Always Use HTTPS On | HTTP 301 |
| HSTS | 同上 | Nginx 或 Cloudflare 二选一；先 6 个月 | 不加 preload |
| WAF 自定义 | `Security` → `WAF` → `Custom rules` | W0–W6 | Free 最多 5 条 |
| 限速 | `Security` → `WAF` → `Rate limiting rules` | 登录 5/min、ASR 10/min、WS 30/min | Free 仅 1 条/10 秒 |
| 托管规则 | `Security` → `WAF` → `Managed rules` | Free 用 Free Managed；Pro+ 加 Cloudflare Managed | OWASP 观察后再开 |
| Bot | `Security` → `Settings` → Bot traffic | Free 建议关 BFM；Pro+ 用 SBFM | BFM 不能 Skip |
| DDoS | `Security` → `DDoS` / `Settings` | HTTP DDoS 默认开；非企业 1 条 override | 不随便调灵敏度 |
| 缓存 | `Caching` → `Cache Rules` | API/WS/docs/PWA 入口 Bypass；assets 缓存 | 最后匹配赢 |
| 响应头 | `Rules` → `Transform Rules` → `Modify response header` | 只补 Nginx 没设的；Set 不 Add | 避免重复 |
| WebSocket | `Network` → `WebSockets` | On | 全套餐支持 |
| Turnstile | 账户级 `Turnstile` | 可选，仅登录 | 不改 JWT |

### 13.2 变更记录模板

```markdown
### CHG-YYYYMMDD-XX：<一句话变更>
- 日期/时间（Asia/Shanghai）：
- 操作人：
- 类型/控制台路径或规则 ID：
- 变更前/变更后（表达式或值）：
- 影响范围、原因与工单：
- 验证命令与结果：
- 观察窗口/回滚步骤：
- 遗留风险：
```

### 13.3 上线后 30 分钟观察

- [ ] `Security` → `Events` 没有异常 403/429，命中规则名符合预期。
- [ ] Traffic 5xx 未上升；Nginx 无大量 499/502/504。
- [ ] `/assets/*` 以 HIT 为主；`/api/*`、`/sw.js` 为 DYNAMIC/BYPASS。
- [ ] 登录、聊天、WS、ASR 四条链路各跑一遍；WS 连续在线 5 分钟无 1006；手机 PWA 能更新（改一次 `sw.js` 验证）。
- [ ] 办公网/家庭宽带/手机 4G 各访问一次，无限速误伤；源站 CPU/内存/Redis 正常。
- [ ] HSTS 只有 1 个；CSP 没有因 Cloudflare 注入脚本报错。

## 参考

- DNS/SSL/Origin CA/HSTS：<https://developers.cloudflare.com/dns/proxy-status/>、<https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/full-strict/>、<https://developers.cloudflare.com/ssl/origin-configuration/origin-ca/>、<https://developers.cloudflare.com/ssl/edge-certificates/additional-options/http-strict-transport-security/>
- WAF：<https://developers.cloudflare.com/waf/custom-rules/>、<https://developers.cloudflare.com/waf/rate-limiting-rules/>、<https://developers.cloudflare.com/waf/managed-rules/>
- Bot：<https://developers.cloudflare.com/bots/get-started/bot-fight-mode/>、<https://developers.cloudflare.com/bots/get-started/super-bot-fight-mode/>
- WebSocket/连接超时：<https://developers.cloudflare.com/network/websockets/>、<https://developers.cloudflare.com/fundamentals/reference/connection-limits/>
- 缓存：<https://developers.cloudflare.com/cache/concepts/default-cache-behavior/>、<https://developers.cloudflare.com/cache/how-to/cache-rules/settings/>、<https://developers.cloudflare.com/cache/how-to/cache-rules/order/>
- Turnstile/错误码：<https://developers.cloudflare.com/turnstile/get-started/server-side-validation/>、<https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1016/>
- Cloudflare IP 段：<https://api.cloudflare.com/client/v4/ips>
