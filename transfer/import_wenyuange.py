#!/usr/bin/env python3
"""Import wenyuange classical txt repos (儒藏、诗藏等) into mopan-site."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper.classics_html import (
    DEFAULT_PREVIEW_CHARS,
    github_urls,
    txt_excerpt,
    txt_preview_html,
    txt_to_content_html,
)

REPO_LABELS = {
    "ru": "儒藏",
    "poem": "诗藏",
    "dao": "道藏",
    "fo": "佛藏",
    "zi": "子藏",
    "yi": "易藏",
    "ji": "集藏",
    "history": "史藏",
    "medicine": "医藏",
    "art": "艺藏",
}


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def ensure_clone(repo: str, dest: Path, branch: str) -> None:
    if (dest / ".git").exists():
        print(f"  [skip clone] {dest}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/wenyuange/{repo}.git"
    print(f"  [clone] {url} -> {dest}")
    subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", branch, url, str(dest)],
        check=True,
    )


def iter_txt_files(repo_dir: Path) -> list[Path]:
    return sorted(p for p in repo_dir.rglob("*.txt") if p.is_file())


def import_repo(
    repo: str,
    repo_dir: Path,
    *,
    classics_prefix: str,
    pan_type: str,
    site_root: Path,
    limit: int = 0,
    preview: bool = True,
    preview_chars: int = DEFAULT_PREVIEW_CHARS,
    github_user: str = "wenyuange",
    branch: str = "master",
) -> dict[str, int]:
    sys.path.insert(0, str(site_root))
    from app.database import upsert_resource  # noqa: WPS433

    lib = REPO_LABELS.get(repo, repo)
    stats = {"files": 0, "inserted": 0, "updated": 0, "errors": 0}
    files = iter_txt_files(repo_dir)
    if limit > 0:
        files = files[:limit]

    for path in files:
        rel = path.relative_to(repo_dir).as_posix()
        source_ref = f"wenyuange/{repo}/{rel}"
        parts = path.relative_to(repo_dir).parts
        sub = " > ".join(parts[:-1]) if len(parts) > 1 else lib
        category = f"{lib} > {sub}" if sub != lib else lib
        title = path.stem
        pan_save_path = f"{classics_prefix.rstrip('/')}/{lib}/{rel}"

        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"  [error] read {rel}: {exc}", file=sys.stderr)
            stats["errors"] += 1
            continue

        stats["files"] += 1
        gh = github_urls(source_ref, branch=branch, user=github_user) or {}
        if preview:
            content = txt_preview_html(text, max_chars=preview_chars)
            pan_url = gh.get("blob", "")
            ext_pan_type = "github"
            link_status = "preview"
        else:
            content = txt_to_content_html(text)
            pan_url = ""
            ext_pan_type = pan_type
            link_status = "on-site"

        result = upsert_resource(
            title=title,
            content_html=content,
            excerpt=txt_excerpt(text),
            category=category,
            channel="classics",
            source_ref=source_ref,
            pan_save_path=pan_save_path,
            pan_url=pan_url,
            pan_type=ext_pan_type,
            link_status=link_status,
            replace_content=True,
        )
        stats[result] += 1
        if stats["files"] % 200 == 0:
            print(f"    ... {stats['files']} files")

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Import wenyuange classics into mopan-site")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--repos", default="", help="Comma repos, default from config")
    parser.add_argument("--limit", type=int, default=0, help="Max files per repo (0=all)")
    parser.add_argument("--no-clone", action="store_true")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Import full text for in-site reading (large DB)",
    )
    parser.add_argument(
        "--preview-chars",
        type=int,
        default=0,
        help="Preview length (0 = config default)",
    )
    args = parser.parse_args()

    config = load_config(Path(args.config))
    classics = config.get("classics", {})
    pan = config.get("pan", {})
    site_root = Path(config["site"]["root"]).expanduser()
    clone_dir = Path(classics.get("clone_dir", "~/mopan-data/classics")).expanduser()
    branch = classics.get("branch", "master")
    repos = [r.strip() for r in (args.repos or "").split(",") if r.strip()]
    if not repos:
        repos = list(classics.get("repos") or ["ru", "poem"])

    classics_prefix = pan.get("classics_prefix", "/魔盘/古典藏书")
    pan_type = pan.get("type", "quark")
    account = pan.get("account", "main")
    github_user = classics.get("github_user", "wenyuange")
    preview = not args.full and classics.get("mode", "preview") != "full"
    preview_chars = args.preview_chars or int(classics.get("preview_chars", DEFAULT_PREVIEW_CHARS))
    print(f"[mopan] wenyuange import · repos={repos}")
    print(f"[mopan] 模式: {'预览+GitHub' if preview else '全文站内'} · 预览 {preview_chars} 字")
    print(f"[mopan] 网盘: {pan_type} · 账号: {account}（仅第一个夸克盘，不用第二个）")
    print(f"[mopan] 备份路径前缀: {classics_prefix}")
    if preview:
        print("[mopan] 正文仅摘录预览；完整 txt 链到 GitHub 下载")
    else:
        print("[mopan] 古典文献全文站内阅读；若要备份请上传到上述路径")

    sys.path.insert(0, str(site_root))
    from app.database import init_db  # noqa: WPS433

    init_db(site_root / "data" / "site.db")

    totals = {"files": 0, "inserted": 0, "updated": 0, "errors": 0}
    for repo in repos:
        dest = clone_dir / repo
        if not args.no_clone:
            ensure_clone(repo, dest, branch)
        if not dest.is_dir():
            print(f"[error] missing repo dir: {dest}", file=sys.stderr)
            return 1
        print(f"[import] {repo} ({REPO_LABELS.get(repo, repo)})")
        stats = import_repo(
            repo,
            dest,
            classics_prefix=classics_prefix,
            pan_type=pan_type,
            site_root=site_root,
            limit=args.limit,
            preview=preview,
            preview_chars=preview_chars,
            github_user=github_user,
            branch=branch,
        )
        for k, v in stats.items():
            totals[k] += v
        print(f"  files={stats['files']} inserted={stats['inserted']} updated={stats['updated']}")

    print("\n--- summary ---")
    print(f"  total_files: {totals['files']}")
    print(f"  inserted: {totals['inserted']}, updated: {totals['updated']}, errors: {totals['errors']}")
    print(f"  site: http://localhost:{config['site'].get('port', 8083)}/?channel=classics")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
