#!/usr/bin/env python3
"""Export discover channel from mopan-site to committed JSON for GitHub / static build."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description="Export discover channel JSON for mopan-site")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    site_root = Path(config["site"]["root"]).expanduser()
    sys.path.insert(0, str(site_root))

    from app.database import init_db, list_category_counts, list_resources  # noqa: WPS433

    db_path = site_root / "data" / "site.db"
    init_db(db_path)

    rows = list_resources(channel="discover", limit=100_000, offset=0)
    category_counts = list_category_counts(channel="discover")

    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "channel": "discover",
        "total": len(rows),
        "category_counts": category_counts,
        "resources": [
            {
                "id": r.id,
                "wp_id": r.wp_id,
                "title": r.title,
                "category": r.category,
                "excerpt": r.excerpt,
                "content_html": r.content_html,
                "published_at": r.published_at,
                "link_status": r.link_status,
                "updated_at": r.updated_at,
            }
            for r in rows
        ],
    }

    out_dir = site_root / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    discover_path = out_dir / "discover.json"
    meta_path = out_dir / "sync_meta.json"
    discover_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta_path.write_text(
        json.dumps(
            {
                "last_export": payload["exported_at"],
                "discover_total": payload["total"],
                "source": "ahhhhfs.com",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"exported: {payload['total']} discover articles")
    print(f"file: {discover_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
