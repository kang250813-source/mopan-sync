#!/usr/bin/env bash
# LINUX DO 网盘资源 → 本地 JSON / 可选导入魔盘
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

MODE="${1:-sync}"
PAGES="${2:-1}"
DELAY="${LINUXDO_DELAY:-12}"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

case "$MODE" in
  crawl|0)
    PAGES="${2:-0}"
    echo "== 仅抓取 LINUX DO RSS 到本地（${PAGES} 页，0=翻到底）=="
    .venv/bin/python scraper/linuxdo.py --pages "$PAGES" --delay "$DELAY" --merge
    ;;
  sync)
    echo "== 抓取 LINUX DO RSS（${PAGES} 页）=="
    .venv/bin/python scraper/linuxdo.py --pages "$PAGES" --delay "$DELAY" --merge
    echo ""
    echo "== 导入魔盘站（仅符合频道）=="
    .venv/bin/python transfer/import_linuxdo.py
    ;;
  *)
    echo "用法: $0 [sync|crawl] [页数]"
    echo "  crawl 0  — 翻页到底，只存本地 data/linuxdo_topics.json"
    exit 1
    ;;
esac
