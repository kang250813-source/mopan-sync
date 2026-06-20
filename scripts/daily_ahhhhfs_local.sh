#!/usr/bin/env bash
# 每日本地：增量抓取 ahhhhfs → 生成本地收件箱（不上站、不推 GitHub）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CRAWL_DAYS="${CRAWL_DAYS:-7}"
INBOX_DAYS="${INBOX_DAYS:-30}"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR" "$ROOT/data"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

after_date="$(python3 - <<PY
from datetime import datetime, timedelta, timezone
days = int("${CRAWL_DAYS}")
print((datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00"))
PY
)"

echo "==> [1/2] 增量抓取 ahhhhfs（after ${after_date}）..."
.venv/bin/python -m scraper --after "$after_date"

echo ""
echo "==> [2/2] 生成本地收件箱（近 ${INBOX_DAYS} 天）..."
.venv/bin/python transfer/export_ahhhhfs_inbox.py --days "$INBOX_DAYS"

now_iso="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
python3 - <<PY
import json
from pathlib import Path
state = {
    "last_local_sync": "$now_iso",
    "crawl_after": "$after_date",
    "crawl_days": int("$CRAWL_DAYS"),
    "inbox_days": int("$INBOX_DAYS"),
    "inbox_json": "data/ahhhhfs_inbox.json",
    "inbox_md": "data/ahhhhfs_inbox.md",
}
Path("$ROOT/data/ahhhhfs_local_state.json").write_text(
    json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
PY

echo ""
echo "完成。本地浏览："
echo "  ${ROOT}/data/ahhhhfs_inbox.md"
echo "  ${ROOT}/data/ahhhhfs_inbox.json"
