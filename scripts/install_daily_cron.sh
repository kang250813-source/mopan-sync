#!/usr/bin/env bash
# 兼容旧名：转调 install_daily_site_sync_cron.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT/scripts/install_daily_site_sync_cron.sh" "$@"
