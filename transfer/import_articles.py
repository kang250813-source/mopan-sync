#!/usr/bin/env python3
"""Import ahhhhfs articles into mopan-site (content on our pages, no outbound source links)."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper.sanitize_content import sanitize_content_html


def _primary_category(conn: sqlite3.Connection, categories_json: str | None) -> str:
    try:
        cat_ids = json.loads(categories_json or "[]")
    except json.JSONDecodeError:
        cat_ids = []
    if not cat_ids:
        return "其他"
    row = conn.execute(
        "SELECT name FROM categories WHERE wp_id = ?",
        (cat_ids[0],),
    ).fetchone()
    return row["name"] if row else "其他"


def main() -> int:
    parser = argparse.ArgumentParser(description="Import articles with content to mopan-site")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--days",
        type=int,
        default=0,
        help="Only import articles modified within the last N days (0 = all)",
    )
    parser.add_argument(
        "--since",
        default="",
        help="Only import articles with modified_at >= this ISO timestamp",
    )
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    db_path = ROOT / config["database"]["path"]
    site_root = Path(os.environ.get("SITE_ROOT") or config["site"]["root"]).expanduser()
    pan_type = config.get("pan", {}).get("type", "quark")

    sys.path.insert(0, str(site_root))
    from app.database import init_db, upsert_resource  # noqa: WPS433

    init_db(site_root / "data" / "site.db")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    sql = "SELECT * FROM articles"
    params: list[str] = []
    if args.since:
        sql += " WHERE modified_at >= ?"
        params.append(args.since)
    elif args.days > 0:
        sql += " WHERE modified_at >= datetime('now', ?)"
        params.append(f"-{args.days} days")
    sql += " ORDER BY published_at DESC"
    if args.limit > 0:
        sql += f" LIMIT {args.limit}"
    rows = conn.execute(sql, params).fetchall()

    stats = {"inserted": 0, "updated": 0}
    for row in rows:
        content = sanitize_content_html(row["content_html"])
        category = _primary_category(conn, row["categories_json"])
        result = upsert_resource(
            title=row["title"],
            content_html=content,
            category=category,
            excerpt=row["excerpt"],
            published_at=row["published_at"],
            pan_url="",
            pan_type=pan_type,
            link_status="pending",
            wp_id=int(row["wp_id"]),
            channel="discover",
        )
        stats[result] += 1
    conn.close()

    print(f"imported: {len(rows)}")
    print(f"inserted: {stats['inserted']}, updated: {stats['updated']}")
    print(f"site: http://localhost:{config['site'].get('port', 8083)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
