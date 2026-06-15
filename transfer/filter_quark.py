#!/usr/bin/env python3
"""Build transfer queue from scraped ahhhhfs quark links."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper.db import ArticleDB


def main() -> int:
    parser = argparse.ArgumentParser(description="Filter quark resources into transfer queue")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--export", default="", help="Optional JSON export path")
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    db = ArticleDB(ROOT / config["database"]["path"])
    prefix = config.get("quark", {}).get("save_path_prefix", "/魔盘")
    stats = db.build_transfer_queue(save_path_prefix=prefix)

    print("--- filter summary ---")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    print(f"  queue_total: {db.total_transfer_queue()}")
    print(f"  status: {db.transfer_stats()}")

    if args.export:
        out = Path(args.export)
        conn_rows = []
        import sqlite3

        conn = sqlite3.connect(ROOT / config["database"]["path"])
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT * FROM transfer_queue ORDER BY published_at DESC"):
            conn_rows.append(dict(row))
        conn.close()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(conn_rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  exported: {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
