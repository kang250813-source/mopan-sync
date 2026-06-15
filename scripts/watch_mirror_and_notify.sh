#!/usr/bin/env bash
# Wait for mirror_wenyuange.sh to finish, retry failures, then signal completion.
set -eo pipefail

TARGET="${TARGET_USER:-kang250813-source}"
LOG="/tmp/mirror-watch.log"
REPOS=(ru poem dao fo zi yi ji history medicine art)

log() { echo "$(date '+%H:%M:%S') $*" | tee -a "$LOG"; }

min_kb() {
  case "$1" in
    ru|poem) echo 100000 ;;
    dao) echo 40000 ;;
    fo) echo 150000 ;;
    zi) echo 200000 ;;
    yi) echo 30000 ;;
    ji) echo 400000 ;;
    history) echo 500000 ;;
    medicine) echo 80000 ;;
    art) echo 20000 ;;
    *) echo 10000 ;;
  esac
}

check_repo() {
  gh api "repos/${TARGET}/$1" --jq '.size' 2>/dev/null || echo 0
}

log "等待 mirror 脚本结束..."
while pgrep -f "scripts/mirror_wenyuange.sh" >/dev/null 2>&1; do
  sleep 30
done
log "mirror 脚本已退出，检查 GitHub..."

failed=()
for repo in "${REPOS[@]}"; do
  size=$(check_repo "$repo")
  min=$(min_kb "$repo")
  if (( size < min )); then
    failed+=("$repo")
    log "  ✗ $repo: ${size}KB (need >=${min}KB)"
  else
    log "  ✓ $repo: ${size}KB"
  fi
done

if ((${#failed[@]})); then
  log "补传: ${failed[*]}"
  cd "$HOME/mopan-sync"
  ONLY_REPOS="${failed[*]// /,}" ./scripts/mirror_wenyuange.sh >>"$LOG" 2>&1 || true
  failed=()
  for repo in "${REPOS[@]}"; do
    size=$(check_repo "$repo")
    min=$(min_kb "$repo")
    if (( size < min )); then failed+=("$repo"); fi
  done
fi

if ((${#failed[@]})); then
  log "MIRROR_NOTIFY_FAIL repos=${failed[*]}"
  echo "FAIL:${failed[*]}" > /tmp/mirror-notify-status.txt
else
  log "MIRROR_NOTIFY_OK all 10 repos on GitHub"
  echo "OK" > /tmp/mirror-notify-status.txt
  cd "$HOME/mopan-sync"
  ./scripts/import_classics_preview.sh >>"$LOG" 2>&1 || true
fi
