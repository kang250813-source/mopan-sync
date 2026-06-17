#!/usr/bin/env bash
# 每日：抓取 ahhhhfs → 导入发现频道 → 导出 JSON → 构建静态站 → 推送 GitHub
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE_ROOT="${SITE_ROOT:-$HOME/mopan-site}"
CRAWL_DAYS="${CRAWL_DAYS:-14}"
IMPORT_DAYS="${IMPORT_DAYS:-14}"
PUSH_GITHUB="${PUSH_GITHUB:-1}"
BASE_PATH="${BASE_PATH:-/}"

cd "$ROOT"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

if [[ ! -d "$SITE_ROOT/.venv" ]]; then
  python3 -m venv "$SITE_ROOT/.venv"
  "$SITE_ROOT/.venv/bin/pip" install -q -r "$SITE_ROOT/requirements.txt"
fi

STATE_FILE="$ROOT/data/discover_sync_state.json"
mkdir -p "$ROOT/data" "$ROOT/logs"

after_date="$(python3 - <<'PY'
from datetime import datetime, timedelta, timezone
days = int(__import__("os").environ.get("CRAWL_DAYS", "14"))
dt = datetime.now(timezone.utc) - timedelta(days=days)
print(dt.strftime("%Y-%m-%dT00:00:00"))
PY
)"

echo "==> [1/5] 增量抓取 ahhhhfs（after ${after_date}）..."
.venv/bin/python -m scraper --after "$after_date"

echo ""
echo "==> [2/5] 导入发现频道（近 ${IMPORT_DAYS} 天修订）..."
.venv/bin/python transfer/import_articles.py --days "$IMPORT_DAYS"

echo ""
echo "==> [3/6] 导出全站数据（发现/K12/AI/藏书/短剧）..."
.venv/bin/python transfer/export_site_data.py

echo ""
echo "==> [4/6] 构建 GitHub Pages 静态站（全频道）..."
BASE_PATH="$BASE_PATH" "$SITE_ROOT/.venv/bin/python" "$SITE_ROOT/scripts/build_static.py"

echo "==> [5/6] 记录同步状态..."
now_iso="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
python3 - <<PY
import json
from pathlib import Path
state = {
    "last_sync": "$now_iso",
    "crawl_after": "$after_date",
    "crawl_days": int("$CRAWL_DAYS"),
    "import_days": int("$IMPORT_DAYS"),
}
Path("$STATE_FILE").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

if [[ "$PUSH_GITHUB" != "1" ]]; then
  echo ""
  echo "完成（未推送 GitHub，PUSH_GITHUB=0）"
  exit 0
fi

echo ""
echo "==> [6/6] 提交并推送 GitHub..."

push_repo() {
  local repo_path="$1"
  local msg="$2"
  if [[ ! -d "$repo_path/.git" ]]; then
    echo "skip: $repo_path 不是 git 仓库"
    return 0
  fi
  cd "$repo_path"
  if git diff --quiet && git diff --cached --quiet && [[ -z "$(git ls-files --others --exclude-standard)" ]]; then
    echo "  $(basename "$repo_path"): 无变更"
    return 0
  fi
  git add -A
  git commit -m "$msg" || true
  git push origin HEAD
  echo "  $(basename "$repo_path"): 已推送"
}

push_repo "$SITE_ROOT" "chore: daily site sync ${now_iso:0:10}"
push_repo "$ROOT" "chore: daily discover crawl ${now_iso:0:10}"

echo ""
echo "完成。"
echo "  本地: http://localhost:8083/?channel=discover"
echo "  Pages: https://kang250813-source.github.io${BASE_PATH}/"
