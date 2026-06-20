#!/usr/bin/env bash
# 安装每日本地 ahhhhfs 更新（默认 07:00，仅抓本地收件箱）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

CRON_LINE="0 7 * * * ${ROOT}/scripts/daily_ahhhhfs_local.sh >> ${LOG_DIR}/daily_ahhhhfs.log 2>&1"

if crontab -l 2>/dev/null | grep -Fq "daily_ahhhhfs_local.sh"; then
  echo "已存在 ahhhhfs 本地更新定时任务："
  crontab -l | grep "daily_ahhhhfs_local.sh"
  exit 0
fi

( crontab -l 2>/dev/null || true
  echo "$CRON_LINE"
) | crontab -

echo "已安装 crontab（每天 07:00 本地抓取 + 收件箱）："
echo "  $CRON_LINE"
echo ""
echo "日志: $LOG_DIR/daily_ahhhhfs.log"
echo "浏览: ${ROOT}/data/ahhhhfs_inbox.md"
echo "上站: ${ROOT}/scripts/import_ahhhhfs_new.sh 7"
