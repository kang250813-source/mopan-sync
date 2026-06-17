#!/usr/bin/env python3
"""Import archive-only share_organize items (previously 网盘-only) to mopan-site."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from transfer.organize_share_to_mopan import import_to_site
from transfer.quark_client import QuarkClient, load_cookie_from_qas

ARCHIVE_CHANNEL = {
    "short_video": "discover",
    "ebook": "discover",
    "media": "discover",
    "business": "discover",
    "other": "discover",
    "k12": "k12",
}


def load_config() -> dict:
    with (ROOT / "config.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description="Import archive share items to mopan-site")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay", type=float, default=1.2)
    args = parser.parse_args()

    config = load_config()
    manifest_path = ROOT / "data" / "share_organize_manifest.json"
    share_cache_path = ROOT / config["quark"].get("share_cache_path", "data/mopan_share_links.json")
    site_root = Path(config["site"]["root"]).expanduser()
    qas_path = Path(config["pan"]["qas_config"]).expanduser()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    site_db = site_root / "data" / "site.db"
    sys.path.insert(0, str(site_root))
    from app.database import init_db  # noqa: WPS433

    init_db(site_db)
    import sqlite3

    conn = sqlite3.connect(site_db)
    existing_refs = {
        row[0]
        for row in conn.execute(
            "SELECT source_ref FROM resources WHERE source_ref LIKE 'share_organize/%'"
        )
    }
    conn.close()

    items = []
    for row in manifest.get("items", []):
        ref = f"share_organize/{row['bucket']}/{row['fid']}"
        if ref not in existing_refs:
            items.append(row)
    print(f"归档项待上站: {len(items)} 条\n")

    if args.dry_run:
        for row in items:
            ch = ARCHIVE_CHANNEL.get(row["bucket"], "discover")
            print(f"  [{ch}] {row['category']}: {row['name'][:55]}")
        return 0

    cookie = load_cookie_from_qas(qas_path)
    client = QuarkClient(cookie)
    cache: dict[str, str] = {}
    if share_cache_path.exists():
        cache = json.loads(share_cache_path.read_text(encoding="utf-8"))

    stats = {"inserted": 0, "updated": 0, "failed": 0, "skipped": 0}
    for row in items:
        bucket = row["bucket"]
        channel = ARCHIVE_CHANNEL.get(bucket, "discover")
        cache_key = f"mopan/{bucket}/{row['fid']}"
        source_ref = f"share_organize/{bucket}/{row['fid']}"

        sys.path.insert(0, str(site_root))
        from app.database import upsert_resource  # noqa: WPS433

        conn = sqlite3.connect(site_db)
        exists = conn.execute(
            "SELECT id FROM resources WHERE source_ref = ?", (source_ref,)
        ).fetchone()
        conn.close()
        if exists:
            stats["skipped"] += 1
            print(f"  已有: {row['name'][:50]}")
            continue

        try:
            pan_url = None
            if cache_key in cache:
                pan_url = cache[cache_key]
            else:
                for attempt in range(3):
                    try:
                        pan_url = client.create_share_link(row["fid"], row["name"][:80])
                        cache[cache_key] = pan_url
                        break
                    except Exception as exc:
                        if attempt == 2:
                            raise
                        print(f"  重试({attempt + 1}): {row['name'][:40]} — {exc}")
                        time.sleep(2.0 * (attempt + 1))
            print(f"  分享: {row['name'][:50]} → {pan_url}")

            result = import_to_site(
                site_root=site_root,
                title=row["name"],
                pan_url=pan_url,
                channel=channel,
                category=row.get("category") or "网盘资源",
                source_ref=source_ref,
            )
            stats[result] += 1
            row["_imported"] = True
            time.sleep(args.delay)
        except Exception as exc:
            stats["failed"] += 1
            print(f"  失败: {row['name'][:50]} — {exc}")

    share_cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    imported_refs = {
        f"share_organize/{row['bucket']}/{row['fid']}" for row in items if row.get("_imported")
    }
    for row in manifest["items"]:
        ref = f"share_organize/{row['bucket']}/{row['fid']}"
        if ref in imported_refs or ref in existing_refs:
            row["on_site"] = True
            row["channel"] = row.get("channel") or ARCHIVE_CHANNEL.get(row["bucket"], "discover")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"\n完成: inserted={stats['inserted']} updated={stats['updated']} "
        f"failed={stats['failed']} skipped={stats['skipped']}"
    )
    port = config["site"].get("port", 8083)
    print(f"魔盘: http://127.0.0.1:{port}/")
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
