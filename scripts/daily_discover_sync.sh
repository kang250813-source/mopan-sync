#!/usr/bin/env bash
# 兼容旧名：转调 daily_site_sync.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT/scripts/daily_site_sync.sh" "$@"
