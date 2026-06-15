"""Export pending transfer items to quark-auto-save."""

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

TASK_PREFIX = "魔盘-"


def load_config(config_path: Path) -> dict:
    with config_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_qas_config(path: Path) -> dict:
    if not path.exists():
        template = path.parent / "quark_config.template.json"
        if template.exists():
            return json.loads(template.read_text(encoding="utf-8"))
        return {"cookie": [""], "push_config": {}, "plugins": {}, "magic_regex": {}, "tasklist": []}
    return json.loads(path.read_text(encoding="utf-8"))


def existing_share_urls(tasklist: list[dict]) -> set[str]:
    urls: set[str] = set()
    for task in tasklist:
        shareurl = task.get("shareurl", "")
        base = shareurl.split("#", 1)[0].strip()
        if base:
            urls.add(base)
    return urls


def main() -> int:
    parser = argparse.ArgumentParser(description="Export mopan transfer queue to QAS")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    db = ArticleDB(ROOT / config["database"]["path"])
    qas_path = ROOT / config["quark"]["qas_config_path"]
    qas_config = load_qas_config(qas_path)
    tasklist = list(qas_config.get("tasklist", []))
    known_urls = existing_share_urls(tasklist)

    pending = db.get_transfer_pending(limit=args.limit)
    added_ids: list[int] = []
    skipped = 0

    for row in pending:
        base_url = row["source_quark_url"].split("#", 1)[0].strip()
        if base_url in known_urls:
            skipped += 1
            continue
        tasklist.append(
            {
                "taskname": f"{TASK_PREFIX}{row['title']}",
                "shareurl": row["source_quark_url"],
                "savepath": row["quark_save_path"],
                "pattern": config["quark"].get("pattern", ".*"),
                "replace": config["quark"].get("replace", ""),
                "enddate": config["quark"].get("enddate", "2099-12-31"),
            }
        )
        known_urls.add(base_url)
        added_ids.append(int(row["id"]))

    print(f"pending_checked: {len(pending)}")
    print(f"added: {len(added_ids)}")
    print(f"skipped_existing: {skipped}")
    print(f"qas_config: {qas_path}")

    if args.dry_run:
        for row in pending[:5]:
            print(f"  - {row['title'][:60]}")
        return 0

    if added_ids:
        qas_config["tasklist"] = tasklist
        qas_path.parent.mkdir(parents=True, exist_ok=True)
        qas_path.write_text(json.dumps(qas_config, ensure_ascii=False, indent=2), encoding="utf-8")
        db.mark_transfer_status(added_ids, "queued")

    print(f"status_counts: {db.transfer_stats()}")
    print(f"QAS WebUI: http://localhost:{config['quark'].get('qas_port', 5006)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
