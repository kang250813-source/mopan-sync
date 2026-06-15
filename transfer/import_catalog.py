#!/usr/bin/env python3
"""Import transfer queue into mopan-site as catalog (source links, pending transfer)."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Import transfer queue catalog to mopan-site")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    db_path = ROOT / config["database"]["path"]
    site_root = Path(config["site"]["root"]).expanduser()

    if site_root not in [Path(p) for p in sys.path]:
        sys.path.insert(0, str(site_root))
    from app.database import init_db, upsert_resource  # noqa: WPS433

    init_db(site_root / "data" / "site.db")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    sql = "SELECT * FROM transfer_queue ORDER BY published_at DESC"
    if args.limit > 0:
        sql += f" LIMIT {args.limit}"
    rows = conn.execute(sql).fetchall()
    conn.close()

    stats = {"inserted": 0, "updated": 0}
    for row in rows:
        result = upsert_resource(
            title=row["title"],
            quark_url=row["source_quark_url"],
            category=row["category"],
            excerpt=row["excerpt"],
            source_url=row["source_article_url"],
            published_at=row["published_at"],
            link_status="source",
        )
        stats[result] += 1

    print(f"imported: {len(rows)}")
    print(f"inserted: {stats['inserted']}, updated: {stats['updated']}")
    print(f"site: http://localhost:{config['site'].get('port', 8083)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
