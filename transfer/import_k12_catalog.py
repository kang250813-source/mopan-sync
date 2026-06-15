#!/usr/bin/env python3
"""Import K12/education Quark catalogs from haers/zhao_resource markdown docs."""

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

CATALOGS = {
    "student-education": {
        "file": "student-education.md",
        "bundle_title": "学生教育全套合集",
        "bundle_category": "学生教育",
        "source_prefix": "k12/zhao/student",
    },
    "career-development": {
        "file": "career-development.md",
        "bundle_title": "职业考试与职场提升合集",
        "bundle_category": "升学考试",
        "source_prefix": "k12/zhao/career",
    },
}

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


def fetch_markdown(name: str) -> str:
    meta = CATALOGS[name]
    url = f"{GITHUB_RAW}/{meta['file']}"
    with httpx.Client(timeout=60.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text


def infer_category(title: str, catalog: str) -> str:
    text = title.strip()
    if text.upper().startswith("TED"):
        return "TED"
    for prefix in ("学前", "小学", "初中", "高中"):
        if text.startswith(prefix):
            return prefix
    if text.startswith("语言") or "英语" in text[:24]:
        return "语言学习"
    if text.startswith("考研"):
        return "考研"
    if text.startswith("二建") or text.startswith("G照"):
        return "职业资格"
    if text.startswith("职场"):
        return "职场提升"
    if text.startswith("CAD"):
        return "技能课程"
    if text.startswith("资料"):
        return "课程资料"
    if catalog == "student-education":
        return "学生教育"
    return "其他"


def parse_catalog(md: str, catalog: str) -> list[dict]:
    meta = CATALOGS[catalog]
    entries: list[dict] = []

    bundle = BUNDLE_RE.search(md)
    if bundle:
        url = bundle.group(1).split("?")[0]
        share_id = SHARE_ID_RE.search(url)
        if share_id:
            entries.append(
                {
                    "title": meta["bundle_title"],
                    "category": meta["bundle_category"],
                    "excerpt": f"小赵资源站 · {meta['bundle_title']}，一键打开全部子目录。",
                    "pan_url": url,
                    "source_ref": f"{meta['source_prefix']}/bundle/{share_id.group(1)}",
                }
            )

    for title, _path_url, open_url in ROW_RE.findall(md):
        title = title.strip()
        if title in ("资源", "---") or title.startswith("分类"):
            continue
        url = open_url.split("?")[0]
        share_id = SHARE_ID_RE.search(url)
        if not share_id:
            continue
        category = infer_category(title, catalog)
        entries.append(
            {
                "title": title,
                "category": category,
                "excerpt": f"夸克网盘 · {category} · 来源小赵资源站（kuake.netlify.app）",
                "pan_url": url,
                "source_ref": f"{meta['source_prefix']}/{share_id.group(1)}",
            }
        )
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(description="Import zhao_resource education catalogs to K12")
    parser.add_argument(
        "--catalog",
        action="append",
        choices=sorted(CATALOGS),
        help="Catalog to import (repeatable; default: all education catalogs)",
    )
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    catalogs = args.catalog or list(CATALOGS)
    config = load_config()
    site_root = Path(config["site"]["root"]).expanduser()
    pan_type = config.get("pan", {}).get("type", "quark")
    published_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    all_entries: list[dict] = []
    for name in catalogs:
        md = fetch_markdown(name)
        entries = parse_catalog(md, name)
        print(f"[{name}] parsed {len(entries)} entries")
        all_entries.extend(entries)

    if args.dry_run:
        for entry in all_entries[:10]:
            print(f"  - [{entry['category']}] {entry['title'][:50]}")
        if len(all_entries) > 10:
            print(f"  ... and {len(all_entries) - 10} more")
        return 0

    sys.path.insert(0, str(site_root))
    from app.database import init_db, upsert_resource  # noqa: WPS433

    init_db(site_root / "data" / "site.db")
    stats = {"inserted": 0, "updated": 0}
    for entry in all_entries:
        result = upsert_resource(
            title=entry["title"],
            pan_url=entry["pan_url"],
            pan_type=pan_type,
            category=entry["category"],
            excerpt=entry["excerpt"],
            published_at=published_at,
            link_status="own",
            channel="k12",
            source_ref=entry["source_ref"],
        )
        stats[result] += 1

    port = config["site"].get("port", 8083)
    print(f"\n完成 inserted={stats['inserted']} updated={stats['updated']} total={len(all_entries)}")
    print(f"K12 频道: http://localhost:{port}/?channel=k12")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
