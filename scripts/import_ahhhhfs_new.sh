#!/usr/bin/env bash
# 把近 N 天 ahhhhfs 文章导入魔盘发现频道（挑选满意后再跑）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
DAYS="${1:-7}"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

echo "==> 导入近 ${DAYS} 天 ahhhhfs 到魔盘发现频道..."
.venv/bin/python transfer/import_articles.py --days "$DAYS"

echo ""
echo "==> 刷新收件箱状态..."
.venv/bin/python transfer/export_ahhhhfs_inbox.py
