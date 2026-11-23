#!/usr/bin/env bash
# =============================================================================
# DeepSeek Chatbot 一键部署脚本（Linux / macOS / WSL）
#
# 用法：
#   ./deploy.sh              # 构建并启动（首次会引导填写 API Key / 生成管理员）
#   ./deploy.sh --no-build   # 跳过镜像构建，直接重启容器
#   ./deploy.sh --help
# =============================================================================
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
RED="\033[31m"
CYAN="\033[36m"
RESET="\033[0m"

log() { printf "${CYAN}[deploy]${RESET} %s\n" "$*"; }
ok() { printf "${GREEN}[ok]${RESET} %s\n" "$*"; }
warn() { printf "${YELLOW}[warn]${RESET} %s\n" "$*"; }
die() { printf "${RED}[error]${RESET} %s\n" "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
DeepSeek Chatbot 一键部署

用法：
  ./deploy.sh              构建镜像并启动全部服务
  ./deploy.sh --no-build   跳过构建，直接启动/重启
  ./deploy.sh --help       显示帮助

首次运行会：
  1. 从 .env.example 生成 .env
  2. 自动生成 SECRET_KEY、PostgreSQL 密码、管理员初始密码
  3. 询问 DEEPSEEK_API_KEY（可留空，稍后再填）
  4. 构建并启动 db / redis / backend / frontend
  5. 等待健康检查通过并打印访问地址与管理员账号
EOF
}

NO_BUILD=0
for arg in "$@"; do
  case "$arg" in
    --no-build) NO_BUILD=1 ;;
    --help|-h) usage; exit 0 ;;
    *) die "未知参数：$arg（使用 --help 查看用法）" ;;
  esac
done

# ---------- 环境检查 ----------
command -v docker >/dev/null 2>&1 || die "未找到 docker，请先安装 Docker Engine 或 Docker Desktop"

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  die "未找到 docker compose，请安装 Docker Compose v2"
fi

# 检测 Cloudflare Origin Certificate；存在则自动叠加 HTTPS 覆盖配置
COMPOSE_FILES=(-f docker-compose.yml)
HTTPS_ENABLED=0
if [[ -f certs/origin.pem && -f certs/origin.key ]]; then
  COMPOSE_FILES+=(-f docker-compose.https.yml)
  HTTPS_ENABLED=1
fi
COMPOSE_DISPLAY="${COMPOSE[*]} ${COMPOSE_FILES[*]}"
compose() {
  "${COMPOSE[@]}" "${COMPOSE_FILES[@]}" --env-file .env "$@"
}

if ! command -v curl >/dev/null 2>&1; then
  warn "未找到 curl，健康检查将退化为等待 20 秒"
fi

rand_hex() {
  local bytes="${1:-16}"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex "$bytes"
  else
    head -c "$bytes" /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

get_env() {
  local key="$1"
  grep -E "^${key}=" .env 2>/dev/null | tail -n1 | cut -d= -f2- || true
}

set_env() {
  local key="$1" value="$2"
  if grep -qE "^${key}=" .env; then
    awk -v k="$key" -v v="$value" 'BEGIN{FS=OFS="="} $1==k {print k"="v; next} {print}' .env > .env.tmp
    mv .env.tmp .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

# ---------- .env 初始化 ----------
if [[ ! -f .env ]]; then
  [[ -f .env.example ]] || die "缺少 .env.example"
  cp .env.example .env
  chmod 600 .env 2>/dev/null || true
  log "已从 .env.example 生成 .env"
fi

secret="$(get_env SECRET_KEY)"
if [[ -z "$secret" || "$secret" == "please-generate-with-openssl-rand-hex-32" || "$secret" == "change-me" ]]; then
  set_env SECRET_KEY "$(rand_hex 32)"
  log "已生成随机 SECRET_KEY"
fi

pg_pass="$(get_env POSTGRES_PASSWORD)"
if [[ -z "$pg_pass" || "$pg_pass" == "change-me-strong" ]]; then
  pg_pass="$(rand_hex 18)"
  set_env POSTGRES_PASSWORD "$pg_pass"
  log "已生成随机 PostgreSQL 密码"
fi

pg_user="$(get_env POSTGRES_USER)"; pg_user="${pg_user:-chatbot}"
pg_db="$(get_env POSTGRES_DB)"; pg_db="${pg_db:-chatbot}"
current_db="$(get_env DATABASE_URL)"
if [[ -z "$current_db" || "$current_db" == *"change-me-strong"* ]]; then
  set_env DATABASE_URL "postgresql://${pg_user}:${pg_pass}@db:5432/${pg_db}"
fi

api_key="$(get_env DEEPSEEK_API_KEY)"
if [[ -z "$api_key" || "$api_key" == "sk-please-replace-me" ]]; then
  if [[ -t 0 ]]; then
    printf "请输入 DeepSeek API Key（留空可稍后写入 .env）："
    IFS= read -r -s api_key || true
    printf "\n"
  fi
  if [[ -n "$api_key" ]]; then
    set_env DEEPSEEK_API_KEY "$api_key"
    ok "已写入 DEEPSEEK_API_KEY"
  else
    warn "未配置 DEEPSEEK_API_KEY：应用可以启动，但聊天会返回配置错误。"
  fi
fi

# 管理员：生成一个符合密码策略的初始密码；已有则保留
admin_user="$(get_env ADMIN_USERNAME)"; admin_user="${admin_user:-admin}"
admin_pass="$(get_env ADMIN_PASSWORD)"
ADMIN_GENERATED=0
if [[ -z "$admin_pass" || "$admin_pass" == "ChangeMe-123456" ]]; then
  admin_pass="Admin-$(date +%Y%m%d)-$(rand_hex 6)"
  set_env ADMIN_USERNAME "$admin_user"
  set_env ADMIN_PASSWORD "$admin_pass"
  set_env ALLOW_BOOTSTRAP "false"
  ADMIN_GENERATED=1
fi

# 生产环境建议填写公网域名；没有填时同源访问仍然正常
cors="$(get_env CORS_ORIGINS)"
if [[ -n "${PUBLIC_URL:-}" && "$cors" != *"${PUBLIC_URL}"* ]]; then
  set_env CORS_ORIGINS "${cors},${PUBLIC_URL%/}"
  log "已将 PUBLIC_URL 加入 CORS_ORIGINS"
fi

chmod 600 .env 2>/dev/null || true

# ---------- 构建与启动 ----------
log "校验 docker compose 配置…"
compose config -q
ok "配置校验通过"
if [[ "$HTTPS_ENABLED" -eq 1 ]]; then
  log "检测到 certs/origin.pem 与 certs/origin.key，已启用源站 HTTPS（443）"
else
  warn "未检测到 Cloudflare Origin 证书，仅启动 HTTP 版本（Cloudflare Full strict 会报 526）"
fi

if [[ "$NO_BUILD" -eq 0 ]]; then
  log "构建镜像（首次构建需要下载依赖与 Whisper 运行库，约 5-15 分钟）…"
  compose build
else
  log "已指定 --no-build，跳过镜像构建"
fi

log "启动服务…"
compose up -d --remove-orphans

# ---------- 等待健康检查 ----------
app_port="$(get_env APP_PORT)"; app_port="${app_port:-80}"
health_url="http://127.0.0.1:${app_port}/api/health"
log "等待服务就绪：${health_url}"

ready=0
if command -v curl >/dev/null 2>&1; then
  for _ in $(seq 1 60); do
    code="$(curl -s -o /dev/null -w '%{http_code}' "$health_url" || true)"
    if [[ "$code" == "200" ]]; then
      ready=1
      break
    fi
    sleep 2
  done
else
  sleep 20
  ready=1
fi

if [[ "$ready" -eq 1 ]]; then
  ok "服务已就绪"
else
  warn "健康检查尚未通过，请查看日志：${COMPOSE_DISPLAY} logs -f backend"
fi

# 首次生成的管理员密码做一次登录验证；数据库已有管理员时不会覆盖旧密码
ADMIN_LOGIN_CHECKED=0
ADMIN_LOGIN_OK=0
if [[ "$ADMIN_GENERATED" -eq 1 && "$ready" -eq 1 ]] && command -v curl >/dev/null 2>&1; then
  ADMIN_LOGIN_CHECKED=1
  api_base="${health_url%/health}"
  login_code="$(curl -s -o /dev/null -w '%{http_code}' \
    -X POST "${api_base}/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"username\":\"${admin_user}\",\"password\":\"${admin_pass}\"}" || true)"
  if [[ "$login_code" == "200" ]]; then
    ADMIN_LOGIN_OK=1
  fi
fi

# ---------- 输出结果 ----------
host_display="http://127.0.0.1:${app_port}"
if [[ -n "${PUBLIC_URL:-}" ]]; then
  host_display="${PUBLIC_URL%/}"
fi

printf "\n${BOLD}============================================================${RESET}\n"
printf "${BOLD} DeepSeek Chatbot 部署完成${RESET}\n"
printf "${BOLD}============================================================${RESET}\n"
printf "  访问地址     : %s\n" "$host_display"
printf "  API 文档     : %s/docs\n" "$host_display"
printf "  健康检查     : %s/api/health\n" "$host_display"
printf "  源站 HTTPS   : %s\n" "$([[ "$HTTPS_ENABLED" -eq 1 ]] && echo '已启用 443（需 Cloudflare Full strict）' || echo '未启用（仅 HTTP）')"
printf "  管理员账号   : %s\n" "$admin_user"
if [[ "$ADMIN_GENERATED" -eq 1 ]]; then
  if [[ "$ADMIN_LOGIN_CHECKED" -eq 1 && "$ADMIN_LOGIN_OK" -eq 0 ]]; then
    printf "  ${YELLOW}提示：数据库已有管理员，.env 中新生成的密码未生效。${RESET}\n"
    printf "  ${YELLOW}请使用原密码；若已忘记，执行：docker compose exec backend python -m app.cli reset-password --username %s${RESET}\n" "$admin_user"
    printf "  管理员密码   : 未修改（以数据库现有密码为准）\n"
  else
    printf "  管理员密码   : %s\n" "$admin_pass"
    printf "  ${YELLOW}请登录后立即在「设置 → 账号」中修改密码${RESET}\n"
  fi
else
  printf "  管理员密码   : 已存在于 .env（未修改）\n"
fi
printf "\n"
printf "  常用命令：\n"
printf "    %s ps\n" "$COMPOSE_DISPLAY"
printf "    %s logs -f backend\n" "$COMPOSE_DISPLAY"
printf "    %s restart backend\n" "$COMPOSE_DISPLAY"
printf "    ./scripts/backup.sh          # 备份数据库\n"
printf "\n"
printf "  ${YELLOW}上线前请阅读 README 的「运维手册」与 docs/CLOUDFLARE.md${RESET}\n"
printf "${BOLD}============================================================${RESET}\n\n"
