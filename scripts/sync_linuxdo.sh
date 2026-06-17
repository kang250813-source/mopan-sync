#!/usr/bin/env bash
# LINUX DO 网盘资源 → 魔盘（原链索引，不转存小怪盘）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PAGES="${1:-1}"
DELAY="${LINUXDO_DELAY:-12}"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

echo "== 抓取 LINUX DO RSS（${PAGES} 页）=="
.venv/bin/python scraper/linuxdo.py --pages "$PAGES" --delay "$DELAY" --merge

echo ""
echo "== 导入魔盘站（仅符合频道）=="
.venv/bin/python transfer/import_linuxdo.py
