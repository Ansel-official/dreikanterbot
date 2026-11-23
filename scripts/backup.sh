#!/usr/bin/env bash
# =============================================================================
# PostgreSQL 每日备份脚本
#
# 用法：
#   ./scripts/backup.sh              # 备份到 ./backups/
#   BACKUP_DIR=/data/backups ./scripts/backup.sh
#   RETENTION_DAYS=30 ./scripts/backup.sh
#
# 建议加入 crontab：
#   0 3 * * * cd /opt/deepseek-chatbot && ./scripts/backup.sh >> backups/backup.log 2>&1
# =============================================================================
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

[[ -f .env ]] || { echo "未找到 .env，无法读取数据库配置" >&2; exit 1; }

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "未找到 docker compose" >&2
  exit 1
fi

get_env() {
  local key="$1"
  grep -E "^${key}=" .env 2>/dev/null | tail -n1 | cut -d= -f2- || true
}

PG_USER="$(get_env POSTGRES_USER)"; PG_USER="${PG_USER:-chatbot}"
PG_DB="$(get_env POSTGRES_DB)"; PG_DB="${PG_DB:-chatbot}"
BACKUP_DIR="${BACKUP_DIR:-backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
FILE="${BACKUP_DIR}/postgres-${STAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[backup] dumping ${PG_DB} as ${PG_USER} -> ${FILE}"
"${COMPOSE[@]}" --env-file .env exec -T db \
  pg_dump -U "$PG_USER" -d "$PG_DB" --clean --if-exists --no-owner \
  | gzip > "$FILE"

# 校验 gzip 完整性
gzip -t "$FILE"
SIZE="$(du -h "$FILE" | cut -f1)"
echo "[backup] done: ${FILE} (${SIZE})"

find "$BACKUP_DIR" -name 'postgres-*.sql.gz' -type f -mtime +"$RETENTION_DAYS" -print -delete \
  | while read -r old; do echo "[backup] removed old backup: $old"; done

echo "[backup] retention: ${RETENTION_DAYS} days"
