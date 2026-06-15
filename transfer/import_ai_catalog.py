#!/usr/bin/env python3
"""Import AI learning Quark catalogs from haers/zhao_resource into ai_video channel."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GITHUB_RAW = "https://raw.githubusercontent.com/haers/zhao_resource/main/docs"
USER_AGENT = "Mozilla/5.0 (compatible; MopanSync/1.0)"

AI_PREFIXES = {
    "AI通识",
    "AI办公",
    "AI变现",
    "AI绘画",
    "AI视频",
    "AI教程",
    "AIGC",
    "DeepSeek",
    "ChatGPT",
    "Midjourney",
    "StableDiffusion",
    "Cursor",
}

AI_KEYWORD_RE = re.compile(
    r"AI|AIGC|人工智能|DeepSeek|ChatGPT|GPT|大模型|Midjourney|Stable\s*Diffusion|ComfyUI|LLM",
    re.IGNORECASE,
)

ROW_RE = re.compile(
    r"^\|\s*([^|]+?)\s*\|\s*\[`[^`]*`\]\((https://pan\.quark\.cn/s/[a-f0-9]+)\)\s*\|"
    r"\s*\[打开\]\((https://pan\.quark\.cn/s/[a-f0-9]+)\)",
    re.MULTILINE | re.IGNORECASE,
)
BUNDLE_RE = re.compile(
    r"资源汇总链接：\[点击打开[^]]+\]\((https://pan\.quark\.cn/s/[a-f0-9]+)\)",
    re.IGNORECASE,
)
SHARE_ID_RE = re.compile(r"/s/([a-f0-9]+)", re.IGNORECASE)


def load_config() -> dict:
    with (ROOT / "config.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch_markdown() -> str:
    url = f"{GITHUB_RAW}/programming-ai.md"
    with httpx.Client(timeout=60.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text


def title_prefix(title: str) -> str:
    if "-" in title:
        return title.split("-", 1)[0].strip()
    return title[:12]


def is_ai_entry(title: str) -> bool:
    prefix = title_prefix(title)
    if prefix in AI_PREFIXES:
        return True
    if prefix == "编程" and AI_KEYWORD_RE.search(title):
        return True
    if prefix == "软件测试" and AI_KEYWORD_RE.search(title):
        return True
    return False


def infer_category(title: str) -> str:
    prefix = title_prefix(title)
    if prefix in AI_PREFIXES:
        return prefix
    if prefix == "编程":
        return "AI编程"
    if prefix == "软件测试":
        return "AI测试"
    return "AI学习"


def parse_entries(md: str, *, include_all: bool = False) -> list[dict]:
    entries: list[dict] = []

    bundle = BUNDLE_RE.search(md)
    if bundle:
        url = bundle.group(1).split("?")[0]
        share_id = SHARE_ID_RE.search(url)
        if share_id:
            entries.append(
                {
                    "title": "编程开发与AI全套合集",
                    "category": "AI合集",
                    "excerpt": "编程开发与 AI 资源汇总，含 DeepSeek、AIGC、AI 办公与绘画等。",
                    "pan_url": url,
                    "source_ref": f"ai_video/zhao/bundle/{share_id.group(1)}",
                }
            )

    for title, _path_url, open_url in ROW_RE.findall(md):
        title = title.strip()
        if title in ("资源", "---") or title.startswith("分类"):
            continue
        if not include_all and not is_ai_entry(title):
            continue
        url = open_url.split("?")[0]
        share_id = SHARE_ID_RE.search(url)
        if not share_id:
            continue
        category = infer_category(title)
        entries.append(
            {
                "title": title,
                "category": category,
                "excerpt": f"夸克网盘 · {category}",
                "pan_url": url,
                "source_ref": f"ai_video/zhao/{share_id.group(1)}",
            }
        )
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description="Import zhao_resource AI catalogs to ai_video")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--all", action="store_true", help="Include non-AI programming entries too")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config()
    site_root = Path(config["site"]["root"]).expanduser()
    pan_type = config.get("pan", {}).get("type", "quark")
    published_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    md = fetch_markdown()
    entries = parse_entries(md, include_all=args.all)
    print(f"parsed {len(entries)} AI entries")

    if args.dry_run:
        for entry in entries[:12]:
            print(f"  - [{entry['category']}] {entry['title'][:55]}")
        if len(entries) > 12:
            print(f"  ... and {len(entries) - 12} more")
        return 0

    sys.path.insert(0, str(site_root))
    from app.database import init_db, upsert_resource  # noqa: WPS433

    init_db(site_root / "data" / "site.db")
    stats = {"inserted": 0, "updated": 0}
    for entry in entries:
        result = upsert_resource(
            title=entry["title"],
            pan_url=entry["pan_url"],
            pan_type=pan_type,
            category=entry["category"],
            excerpt=entry["excerpt"],
            published_at=published_at,
            link_status="own",
            channel="ai_video",
            source_ref=entry["source_ref"],
        )
        stats[result] += 1

    port = config["site"].get("port", 8083)
    print(f"\n完成 inserted={stats['inserted']} updated={stats['updated']} total={len(entries)}")
    print(f"AI 学习: http://localhost:{port}/?channel=ai_video")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
