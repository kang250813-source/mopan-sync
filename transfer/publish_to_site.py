"""Create mopan Quark share links after QAS transfer and publish to mopan-site."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper.db import ArticleDB
from transfer.quark_client import QuarkClient, QuarkError, load_cookie_from_qas

TASK_PREFIX = "魔盘-"


def load_config() -> dict:
    with (ROOT / "config.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_qas_tasks(qas_path: Path) -> list[dict]:
    data = json.loads(qas_path.read_text(encoding="utf-8"))
    return list(data.get("tasklist", []))


def load_cache(cache_path: Path) -> dict[str, str]:
    if not cache_path.exists():
        return {}
    return json.loads(cache_path.read_text(encoding="utf-8"))


def save_cache(cache: dict[str, str], cache_path: Path) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def task_title(task: dict) -> str:
    name = task.get("taskname", "")
    if name.startswith(TASK_PREFIX):
        return name[len(TASK_PREFIX) :]
    return name


def import_to_site(
    *,
    title: str,
    quark_url: str,
    category: str | None,
    excerpt: str | None,
    source_url: str | None,
    published_at: str | None,
    site_root: Path,
) -> str:
    site_db = site_root / "data" / "site.db"
    if not site_db.exists():
        raise FileNotFoundError(f"站点数据库不存在: {site_db}")

    site_path = str(site_root)
    if site_path not in sys.path:
        sys.path.insert(0, site_path)
    from app.database import upsert_resource  # noqa: WPS433

    return upsert_resource(
        title=title,
        quark_url=quark_url.split("?")[0].strip(),
        category=category,
        excerpt=excerpt,
        source_url=source_url,
        published_at=published_at,
        link_status="own",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish transferred mopan resources to site")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--delay", type=float, default=1.2)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    config = load_config()
    db = ArticleDB(ROOT / config["database"]["path"])
    qas_path = ROOT / config["quark"]["qas_config_path"]
    cache_path = ROOT / config["quark"].get("share_cache_path", "data/mopan_share_links.json")
    site_root = Path(config["site"]["root"]).expanduser()

    cookie = load_cookie_from_qas(qas_path)
    client = QuarkClient(cookie)
    print("验证夸克账号...")
    account = client.get_account_info()
    print(f"  账号: {account.get('nickname') or account.get('mobile') or 'OK'}")

    tasks = load_qas_tasks(qas_path)
    if not tasks:
        print("QAS 任务列表为空，请先运行 export_to_qas.py")
        return 1

    cache = load_cache(cache_path)
    limit = args.limit if args.limit > 0 else len(tasks)
    stats = {"shared": 0, "cached": 0, "inserted": 0, "updated": 0, "failed": 0, "skipped": 0}

    with sqlite3.connect(ROOT / config["database"]["path"]) as conn:
        conn.row_factory = sqlite3.Row
        meta_rows = {
            row["title"]: row
            for row in conn.execute("SELECT * FROM transfer_queue")
        }

    print(f"共 {len(tasks)} 个 QAS 任务，处理 {min(limit, len(tasks))} 个\n")

    for idx, task in enumerate(tasks[:limit], start=1):
        savepath = task.get("savepath", "").strip()
        title = task_title(task)
        if not savepath or not title:
            stats["skipped"] += 1
            continue

        meta = meta_rows.get(title)
        print(f"[{idx}/{limit}] {title[:60]}")

        share_url = None
        if not args.force and savepath in cache:
            share_url = cache[savepath]
            stats["cached"] += 1
            print(f"  使用缓存: {share_url}")
        elif args.dry_run:
            print(f"  [dry-run] 将为 {savepath} 创建分享")
            stats["shared"] += 1
            continue
        else:
            try:
                fid = client.get_fid_by_path(savepath)
                if not fid:
                    print(f"  ⚠ 网盘路径不存在（可能尚未转存）: {savepath}")
                    stats["failed"] += 1
                    continue
                share_url = client.create_share_link(fid, title[:120])
                cache[savepath] = share_url
                save_cache(cache, cache_path)
                stats["shared"] += 1
                print(f"  ✓ 分享: {share_url}")
                time.sleep(args.delay)
            except QuarkError as exc:
                print(f"  ✗ 失败: {exc}")
                stats["failed"] += 1
                continue

        if not share_url:
            continue

        try:
            result = import_to_site(
                title=title,
                quark_url=share_url,
                category=meta["category"] if meta else None,
                excerpt=meta["excerpt"] if meta else None,
                source_url=meta["source_article_url"] if meta else None,
                published_at=meta["published_at"] if meta else None,
                site_root=site_root,
            )
            stats[result] += 1
            print(f"  → 魔盘站点: {result}")
            if meta:
                db.mark_transfer_status([int(meta["id"])], "done", mopan_quark_url=share_url)
        except Exception as exc:
            print(f"  ✗ 导入站点失败: {exc}")
            stats["failed"] += 1

    print("\n--- 完成 ---")
    for key, value in stats.items():
        print(f"{key}: {value}")
    port = config["site"].get("port", 8083)
    print(f"站点: http://localhost:{port}")
    return 0 if stats["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
