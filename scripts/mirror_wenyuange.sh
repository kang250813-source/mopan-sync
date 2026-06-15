#!/usr/bin/env bash
# Mirror wenyuange classical repos to your GitHub (one-time / manual re-run).
set -uo pipefail

SOURCE_USER="${SOURCE_USER:-wenyuange}"
TARGET_USER="${TARGET_USER:-kang250813-source}"
WORKDIR="${WORKDIR:-$HOME/mopan-data/mirror-work}"
LOCAL_CLONE_DIR="${LOCAL_CLONE_DIR:-$HOME/mopan-data/classics}"
RETRIES="${RETRIES:-5}"
ONLY_REPOS="${ONLY_REPOS:-}"   # comma list, e.g. dao,fo

declare -A REPO_LABELS=(
  [ru]=儒藏 [poem]=诗藏 [dao]=道藏 [fo]=佛藏 [zi]=子藏
  [yi]=易藏 [ji]=集藏 [history]=史藏 [medicine]=医藏 [art]=艺藏
)
REPOS=(ru poem dao fo zi yi ji history medicine art)

retry() {
  local n=1
  local max="$RETRIES"
  until "$@"; do
    if (( n >= max )); then
      echo "  ✗ failed after ${max} attempts: $*" >&2
      return 1
    fi
    echo "  [retry $((n + 1))/${max}] ..."
    sleep $((n * 8))
    n=$((n + 1))
  done
}

mkdir -p "$WORKDIR"
if [[ -n "$ONLY_REPOS" ]]; then
  IFS=',' read -ra REPOS <<< "$ONLY_REPOS"
fi

echo "[mirror] ${SOURCE_USER} → ${TARGET_USER}"
echo "[mirror] workdir: $WORKDIR"
echo ""

failed=()
for repo in "${REPOS[@]}"; do
  label="${REPO_LABELS[$repo]:-$repo}"
  src="https://github.com/${SOURCE_USER}/${repo}.git"
  dst="https://github.com/${TARGET_USER}/${repo}.git"
  bare="${WORKDIR}/${repo}.git"
  local_clone="${LOCAL_CLONE_DIR}/${repo}"

  echo "========== ${repo} (${label}) =========="

  if retry gh repo view "${TARGET_USER}/${repo}" >/dev/null 2>&1; then
    echo "  [skip create] ${TARGET_USER}/${repo} exists"
  elif retry gh repo create "${TARGET_USER}/${repo}" \
      --public \
      --description "Mirror · ${label} · from ${SOURCE_USER}/${repo} · 古典藏书" \
      --confirm; then
    echo "  [created] ${TARGET_USER}/${repo}"
  else
    echo "  [warn] could not create via gh; will try push anyway"
  fi

  if [[ -d "$bare" ]]; then
    echo "  [update mirror] $bare"
    git -C "$bare" remote set-url origin "$src" 2>/dev/null || true
    if ! retry git -C "$bare" fetch --prune origin; then
      echo "  [reclone] fetch failed, removing $bare"
      rm -rf "$bare"
    fi
  fi

  if [[ ! -d "$bare" ]]; then
    if [[ -d "$local_clone/.git" ]]; then
      echo "  [clone --bare from local] $local_clone"
      if ! retry git clone --bare "file://${local_clone}" "$bare"; then
        failed+=("$repo")
        echo ""
        continue
      fi
    else
      echo "  [clone --mirror] $src"
      if ! retry git clone --mirror "$src" "$bare"; then
        failed+=("$repo")
        echo ""
        continue
      fi
    fi
  fi

  echo "  [push --mirror] → $dst"
  if retry git -C "$bare" push --mirror "$dst"; then
    echo "  ✓ https://github.com/${TARGET_USER}/${repo}"
  else
    failed+=("$repo")
    echo "  ✗ push failed: ${repo}"
  fi
  echo ""
done

echo "--- done ---"
if ((${#failed[@]})); then
  echo "failed repos: ${failed[*]}"
  echo "re-run: ONLY_REPOS=${failed[*]// /,} bash scripts/mirror_wenyuange.sh"
  exit 1
fi
echo "GitHub: https://github.com/${TARGET_USER}?tab=repositories"
echo "Next: ./scripts/import_classics_preview.sh"
