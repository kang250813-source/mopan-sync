#!/usr/bin/env python3
"""Fetch Quark share subfolders and store on K12 / AI resources."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from transfer.quark_share import folder_fid_from_source_ref, list_folder_names


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich resources with Quark folder branches")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--channel", action="append", choices=["k12", "ai_video"], default=[])
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    site_root = Path(config["site"]["root"]).expanduser()
    db_path = site_root / "data" / "site.db"
    channels = args.channel or ["k12", "ai_video"]

    sys.path.insert(0, str(site_root))
    from app.database import init_db  # noqa: WPS433

    init_db(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    placeholders = ",".join("?" for _ in channels)
    sql = f"""
        SELECT id, title, pan_url, source_ref, channel
        FROM resources
        WHERE channel IN ({placeholders}) AND pan_url != ''
        ORDER BY channel, id
    """
    rows = conn.execute(sql, channels).fetchall()
    if args.limit > 0:
        rows = rows[: args.limit]

    branch_cache: dict[tuple[str, str | None], list[str]] = {}
    stats = {"ok": 0, "empty": 0, "fail": 0}

    for row in rows:
        pan_url = (row["pan_url"] or "").split("?")[0].strip()
        if not pan_url:
            continue
        fid = folder_fid_from_source_ref(row["source_ref"])
        cache_key = (pan_url, fid)
        try:
            if cache_key not in branch_cache:
                branch_cache[cache_key] = list_folder_names(pan_url, folder_fid=fid)
            branches = branch_cache[cache_key]
            conn.execute(
                "UPDATE resources SET pan_branches = ?, updated_at = datetime('now') WHERE id = ?",
                (json.dumps(branches, ensure_ascii=False), row["id"]),
            )
            if branches:
                stats["ok"] += 1
                print(f"  ✓ [{row['channel']}] {row['title'][:40]} · {len(branches)} 个分支")
            else:
                stats["empty"] += 1
                print(f"  - [{row['channel']}] {row['title'][:40]} · 无子目录")
        except Exception as exc:
            stats["fail"] += 1
            print(f"  ✗ [{row['channel']}] {row['title'][:40]} · {exc}", file=sys.stderr)

    conn.commit()
    conn.close()
    print(f"\n完成 ok={stats['ok']} empty={stats['empty']} fail={stats['fail']}")
    return 0 if stats["fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
