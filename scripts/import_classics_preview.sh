#!/usr/bin/env bash
# 古典藏书：仅保留开篇摘录 + GitHub 下载链（不存全文）
set -euo pipefail
cd "$(dirname "$0")/.."

.venv/bin/python transfer/import_wenyuange.py --no-clone "$@"

DB="${MOPAN_DB:-$HOME/mopan-site/data/site.db}"
if [[ -f "$DB" ]]; then
  echo ""
  echo "压缩数据库 $DB ..."
  sqlite3 "$DB" "VACUUM;"
  ls -lh "$DB"
fi

echo "完成 → http://localhost:${PORT:-8083}/?channel=classics"
