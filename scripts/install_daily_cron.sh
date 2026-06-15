#!/usr/bin/env bash
# 安装每日 06:00 本地定时任务（发现频道同步）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

CRON_LINE="0 6 * * * ${ROOT}/scripts/daily_discover_sync.sh >> ${LOG_DIR}/daily_discover.log 2>&1"

if crontab -l 2>/dev/null | grep -Fq "daily_discover_sync.sh"; then
  echo "已存在 daily_discover_sync 定时任务："
  crontab -l | grep "daily_discover_sync.sh"
  exit 0
fi

( crontab -l 2>/dev/null || true
  echo "$CRON_LINE"
) | crontab -

echo "已安装 crontab（每天 06:00）："
echo "  $CRON_LINE"
echo ""
echo "日志: $LOG_DIR/daily_discover.log"
echo "手动运行: ${ROOT}/scripts/daily_discover_sync.sh"
