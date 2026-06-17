#!/usr/bin/env python3
"""Import crawled LINUX DO topics into mopan-site (source pan links, no transfer)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_config() -> dict:
    with (ROOT / "config.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import LINUX DO topics to mopan-site")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--input", default="", help="linuxdo_topics.json path")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--all", action="store_true", help="包含不符合频道的条目")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    config = load_config()
    linuxdo = config.get("linuxdo", {})
    in_path = Path(args.input or linuxdo.get("data_path", "data/linuxdo_topics.json"))
    if not in_path.is_absolute():
        in_path = ROOT / in_path

    site_root = Path(config["site"]["root"]).expanduser()
    payload = json.loads(in_path.read_text(encoding="utf-8"))
    topics = list(payload.get("topics") or [])

    if not args.all:
        topics = [t for t in topics if t.get("eligible")]

    topics.sort(key=lambda t: int(t.get("topic_id", 0)), reverse=True)
    if args.limit > 0:
        topics = topics[: args.limit]

    print(f"准备导入 {len(topics)} 条（{'全部' if args.all else '仅符合魔盘'}）\n")

    if args.dry_run:
        for row in topics[:20]:
            ch = row.get("channel") or "-"
            print(f"  [{ch}] {row['title'][:55]} · {row['pan_type']}")
        if len(topics) > 20:
            print(f"  ... 还有 {len(topics) - 20} 条")
        return 0

    sys.path.insert(0, str(site_root))
    from app.database import init_db, upsert_resource  # noqa: WPS433

    init_db(site_root / "data" / "site.db")
    published_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    stats = {"inserted": 0, "updated": 0}

    for row in topics:
        channel = row.get("channel") or "discover"
        excerpt = f"来源 LINUX DO 社区网盘资源，{row.get('pan_type', 'quark')} 直链。"
        result = upsert_resource(
            title=row["title"],
            pan_url=row["pan_url"],
            pan_type=row.get("pan_type", "quark"),
            category=row.get("category") or "网盘资源",
            excerpt=excerpt,
            published_at=row.get("published_at") or published_at,
            link_status="own",
            channel=channel,
            source_ref=row.get("source_ref"),
        )
        stats[result] += 1
        print(f"  {result}: [{channel}] {row['title'][:50]}")

    port = config["site"].get("port", 8083)
    print(f"\n完成 inserted={stats['inserted']} updated={stats['updated']}")
    print(f"魔盘: http://127.0.0.1:{port}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
