#!/usr/bin/env python3
"""Export all mopan-site channels + drama catalog for GitHub Pages."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _resource_dict(resource) -> dict:
    return {
        "id": resource.id,
        "wp_id": resource.wp_id,
        "title": resource.title,
        "category": resource.category,
        "excerpt": resource.excerpt,
        "content_html": resource.content_html,
        "published_at": resource.published_at,
        "link_status": resource.link_status,
        "pan_url": resource.pan_url,
        "pan_type": resource.pan_type,
        "channel": resource.channel,
        "source_ref": resource.source_ref,
        "pan_branches": resource.pan_branches,
        "updated_at": resource.updated_at,
    }


def _drama_dict(drama) -> dict:
    return {
        "id": drama.id,
        "title": drama.title,
        "pan_url": drama.pan_url,
        "published_at": drama.published_at,
        "cover_url": drama.cover_url,
        "tags": list(drama.tags or []),
        "pan_source": getattr(drama, "pan_source", "main"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export full site data for static build")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    site_root = Path(os.environ.get("SITE_ROOT") or config["site"]["root"]).expanduser()
    sys.path.insert(0, str(site_root))

    from app import jupan_bridge  # noqa: WPS433
    from app.config import JUPAN_COVERS_DIR  # noqa: WPS433
    from app.database import (  # noqa: WPS433
        init_db,
        list_category_counts,
        list_classics_library_counts,
        list_resources,
    )

    db_path = site_root / "data" / "site.db"
    init_db(db_path)

    resource_channels = ("discover", "media", "other", "k12", "ai_video", "classics")
    channels: dict[str, dict] = {}
    channel_counts: dict[str, int] = {}

    for channel in resource_channels:
        rows = list_resources(channel=channel, limit=500_000, offset=0)
        if channel == "classics":
            category_counts = list_classics_library_counts()
        else:
            category_counts = list_category_counts(channel=channel)
        channels[channel] = {
            "resources": [_resource_dict(r) for r in rows],
            "category_counts": category_counts,
        }
        channel_counts[channel] = len(rows)
        print(f"  {channel}: {len(rows)}")

    drama_total = jupan_bridge.count_dramas()
    dramas = jupan_bridge.list_dramas(limit=max(drama_total, 1), offset=0)
    channel_counts["drama"] = drama_total
    print(f"  drama: {drama_total}")

    exported_at = datetime.now(timezone.utc).isoformat()
    out_dir = site_root / "data"
    export_dir = out_dir / "export"
    export_dir.mkdir(parents=True, exist_ok=True)

    for channel in resource_channels:
        channel_path = export_dir / f"{channel}.json"
        channel_path.write_text(
            json.dumps(
                {
                    "exported_at": exported_at,
                    "channel": channel,
                    "total": channel_counts[channel],
                    "category_counts": channels[channel]["category_counts"],
                    "resources": channels[channel]["resources"],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    drama_path = export_dir / "drama.json"
    drama_path.write_text(
        json.dumps(
            {
                "exported_at": exported_at,
                "channel": "drama",
                "total": drama_total,
                "dramas": [_drama_dict(d) for d in dramas],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    manifest_path = export_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "exported_at": exported_at,
                "channel_counts": channel_counts,
                "files": {
                    **{ch: f"{ch}.json" for ch in resource_channels},
                    "drama": "drama.json",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    meta_path = out_dir / "sync_meta.json"
    meta_path.write_text(
        json.dumps(
            {
                "last_export": exported_at,
                "channel_counts": channel_counts,
                "source": "mopan-site + duanjuku-site",
                "export_dir": "data/export",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # Backward-compatible discover-only export
    discover_path = out_dir / "discover.json"
    discover_path.write_text(
        json.dumps(
            {
                "exported_at": exported_at,
                "channel": "discover",
                "total": channel_counts.get("discover", 0),
                "category_counts": channels["discover"]["category_counts"],
                "resources": channels["discover"]["resources"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    covers_src = JUPAN_COVERS_DIR
    covers_dst = out_dir / "jupan-covers"
    if covers_src.is_dir():
        if covers_dst.exists():
            shutil.rmtree(covers_dst)
        shutil.copytree(covers_src, covers_dst)
        cover_count = sum(1 for _ in covers_dst.iterdir() if _.is_file())
        print(f"  covers: {cover_count} -> {covers_dst}")

    print(f"exported -> {export_dir}/ (manifest + {len(resource_channels) + 1} channel files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
