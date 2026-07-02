#!/usr/bin/env bash
# 每日全站同步：ahhhhfs + LINUX DO → 导入魔盘 → 导出 → 静态站 → git push
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE_ROOT="${SITE_ROOT:-$HOME/mopan-site}"
export SITE_ROOT
CRAWL_DAYS="${CRAWL_DAYS:-14}"
IMPORT_DAYS="${IMPORT_DAYS:-14}"
LINUXDO_PAGES="${LINUXDO_PAGES:-5}"
LINUXDO_DELAY="${LINUXDO_DELAY:-10}"
PUSH_GITHUB="${PUSH_GITHUB:-1}"
BASE_PATH="${BASE_PATH:-/}"
LOCK_FILE="${LOCK_FILE:-/tmp/mopan-daily-site-sync.lock}"
LOG_TAG="[daily-site-sync $(date '+%F %T')]"

log() { echo "$LOG_TAG $*"; }

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  log "已有同步任务在运行，跳过"
  exit 0
fi

cd "$ROOT"
mkdir -p "$ROOT/data" "$ROOT/logs"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi

if [[ ! -d "$SITE_ROOT/.venv" ]]; then
  python3 -m venv "$SITE_ROOT/.venv"
  "$SITE_ROOT/.venv/bin/pip" install -q -r "$SITE_ROOT/requirements.txt"
fi

log "[0/7] 确保 site.db 已从 data/export 初始化..."
"$SITE_ROOT/.venv/bin/python" "$SITE_ROOT/scripts/bootstrap_site_db.py"

after_date="$(python3 - <<'PY'
from datetime import datetime, timedelta, timezone
days = int(__import__("os").environ.get("CRAWL_DAYS", "14"))
dt = datetime.now(timezone.utc) - timedelta(days=days)
print(dt.strftime("%Y-%m-%dT00:00:00"))
PY
)"

log "开始全站同步（ahhhhfs ${CRAWL_DAYS}d + LINUX DO ${LINUXDO_PAGES} 页）"

log "[1/7] 增量抓取 ahhhhfs（after ${after_date}）..."
.venv/bin/python -m scraper --after "$after_date"

log "[2/7] 导入 ahhhhfs 到发现频道（近 ${IMPORT_DAYS} 天）..."
.venv/bin/python transfer/import_articles.py --days "$IMPORT_DAYS"

log "[3/7] 抓取 LINUX DO RSS（${LINUXDO_PAGES} 页）..."
if ! .venv/bin/python scraper/linuxdo.py --pages "$LINUXDO_PAGES" --delay "$LINUXDO_DELAY" --merge; then
  log "LINUX DO 抓取失败，跳过导入（ahhhhfs 与其它步骤继续）"
else
  log "[4/7] 导入 LINUX DO 网盘资源..."
  .venv/bin/python transfer/import_linuxdo.py
fi

log "[5/7] 导出全站数据..."
.venv/bin/python transfer/export_site_data.py

log "[6/7] 构建 GitHub Pages 静态站..."
BASE_PATH="$BASE_PATH" "$SITE_ROOT/.venv/bin/python" "$SITE_ROOT/scripts/build_static.py"

now_iso="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
today="${now_iso:0:10}"
STATE_FILE="$ROOT/data/discover_sync_state.json"
python3 - <<PY
import json
from pathlib import Path
state = {
    "last_sync": "$now_iso",
    "crawl_after": "$after_date",
    "crawl_days": int("$CRAWL_DAYS"),
    "import_days": int("$IMPORT_DAYS"),
    "linuxdo_pages": int("$LINUXDO_PAGES"),
    "pipeline": "daily_site_sync",
}
Path("$STATE_FILE").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY

if [[ "$PUSH_GITHUB" != "1" ]]; then
  log "完成（未推送 GitHub，PUSH_GITHUB=0）"
  exit 0
fi

log "[7/7] 提交并推送 GitHub..."

push_repo() {
  local repo_path="$1"
  local msg="$2"
  local -a add_paths=("${@:3}")
  if [[ ! -d "$repo_path/.git" ]]; then
    log "skip: $repo_path 不是 git 仓库"
    return 0
  fi
  cd "$repo_path"
  if [[ ${#add_paths[@]} -gt 0 ]]; then
    git add "${add_paths[@]}"
  else
    git add -A
  fi
  if git diff --staged --quiet; then
    log "$(basename "$repo_path"): 无变更"
    return 0
  fi
  git commit -m "$msg"
  git push origin HEAD
  log "$(basename "$repo_path"): 已推送"
}

export GIT_TERMINAL_PROMPT=0
push_repo "$SITE_ROOT" "chore: daily site sync ${today}" \
  docs data/discover.json data/export data/sync_meta.json data/jupan-covers
push_repo "$ROOT" "chore: daily site sync ${today}" data/discover_sync_state.json

log "完成。本地: http://127.0.0.1:8083/ · Pages: https://www.mopan.lol/"
