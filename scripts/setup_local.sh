#!/usr/bin/env bash
# 魔盘 · 一键初始化（筛选 + 导入站点目录）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SITE="$HOME/mopan-site"

echo "== 1/3 筛选夸克资源 =="
"$ROOT/scripts/filter_quark.sh" --export "$ROOT/data/transfer_queue.json"

echo ""
echo "== 2/3 导入魔盘站点目录 =="
if [[ ! -d "$SITE/.venv" ]]; then
  (cd "$SITE" && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt)
fi
"$ROOT/scripts/import_catalog.sh"

echo ""
echo "== 3/3 启动说明 =="
echo "  魔盘站点:  cd ~/mopan-site && ./run.sh"
echo "  QAS 转存:  cd ~/mopan-sync && docker compose up -d"
echo "             打开 http://localhost:5006 配置 Cookie"
echo "             ./scripts/export_to_qas.sh"
echo "  转存完成后: ./scripts/publish_to_site.sh"
