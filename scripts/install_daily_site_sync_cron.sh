#!/usr/bin/env bash
# 安装每日 10:00 全站同步（ahhhhfs + LINUX DO + 静态站 + git push）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/logs"
SYNC_SCRIPT="$ROOT/scripts/daily_site_sync.sh"
mkdir -p "$LOG_DIR"
chmod +x "$SYNC_SCRIPT"

# 每天 10:00（本机时区，通常为北京时间）
CRON_LINE="0 10 * * * ${SYNC_SCRIPT} >> ${LOG_DIR}/daily_site_sync.log 2>&1"

# 移除旧的魔盘同步 cron，避免重复跑
OLD_PATTERNS=(
  "daily_discover_sync.sh"
  "daily_ahhhhfs_local.sh"
  "daily_site_sync.sh"
)

tmp="$(mktemp)"
crontab -l 2>/dev/null | grep -v -F "daily_discover_sync.sh" \
  | grep -v -F "daily_ahhhhfs_local.sh" \
  | grep -v -F "daily_site_sync.sh" > "$tmp" || true
echo "$CRON_LINE" >> "$tmp"
crontab "$tmp"
rm -f "$tmp"

echo "已安装 crontab（每天 10:00 全站同步）："
echo "  $CRON_LINE"
echo ""
echo "日志: ${LOG_DIR}/daily_site_sync.log"
echo "手动试跑: ${SYNC_SCRIPT}"
echo "仅本地不推送: PUSH_GITHUB=0 ${SYNC_SCRIPT}"
