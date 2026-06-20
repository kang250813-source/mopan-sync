#!/usr/bin/env python3
"""Export ahhhhfs articles to local inbox JSON/Markdown for review before site import."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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


def _site_wp_ids(site_db: Path) -> set[int]:
    if not site_db.exists():
        return set()
    conn = sqlite3.connect(site_db)
    rows = conn.execute(
        "SELECT wp_id FROM resources WHERE wp_id IS NOT NULL AND channel = 'discover'"
    ).fetchall()
    conn.close()
    return {int(r[0]) for r in rows if r[0] is not None}


def _pan_links(conn: sqlite3.Connection, wp_id: int) -> list[dict[str, str]]:
    rows = conn.execute(
        """
        SELECT link_type, url FROM links
        WHERE article_wp_id = ? AND link_type IN ('quark', 'baidu', 'aliyun', '123pan')
        ORDER BY CASE link_type WHEN 'quark' THEN 0 WHEN 'baidu' THEN 1 ELSE 2 END
        """,
        (wp_id,),
    ).fetchall()
    return [{"type": r["link_type"], "url": r["url"]} for r in rows]


def export_inbox(
    *,
    db_path: Path,
    site_db: Path,
    days: int,
    out_json: Path,
    out_md: Path,
) -> dict:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    sql = """
        SELECT wp_id, title, url, excerpt, published_at, modified_at, categories_json
        FROM articles
    """
    params: list[str] = []
    if days > 0:
        sql += " WHERE published_at >= datetime('now', ?)"
        params.append(f"-{days} days")
    sql += " ORDER BY published_at DESC"

    rows = conn.execute(sql, params).fetchall()
    on_site = _site_wp_ids(site_db)

    items: list[dict] = []
    for row in rows:
        wp_id = int(row["wp_id"])
        pans = _pan_links(conn, wp_id)
        items.append(
            {
                "wp_id": wp_id,
                "title": row["title"],
                "url": row["url"],
                "category": _primary_category(conn, row["categories_json"]),
                "excerpt": (row["excerpt"] or "")[:200],
                "published_at": row["published_at"],
                "modified_at": row["modified_at"],
                "pan_links": pans,
                "on_site": wp_id in on_site,
            }
        )
    conn.close()

    new_count = sum(1 for i in items if not i["on_site"])
    payload = {
        "source": "ahhhhfs.com",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "total": len(items),
        "on_site": len(items) - new_count,
        "pending_review": new_count,
        "items": items,
    }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# ahhhhfs 本地更新收件箱",
        "",
        f"- 导出时间：{payload['exported_at']}",
        f"- 近 **{days}** 天共 **{len(items)}** 篇",
        f"- 已上魔盘：**{payload['on_site']}** · 待挑选：**{new_count}**",
        "",
        "> 仅本地浏览用。满意后运行：`./scripts/import_ahhhhfs_new.sh`",
        "",
        "---",
        "",
    ]
    for i, item in enumerate(items, 1):
        flag = "✓已上站" if item["on_site"] else "**待挑选**"
        pans = item["pan_links"]
        pan_txt = " · ".join(f"{p['type']}" for p in pans) if pans else "无网盘链"
        pub = (item["published_at"] or "")[:10]
        lines.append(f"## {i}. {item['title']} [{flag}]")
        lines.append(f"- 分类：{item['category']} · 发布：{pub} · 网盘：{pan_txt}")
        lines.append(f"- 原文：{item['url']}")
        if pans:
            lines.append(f"- 夸克/网盘：{pans[0]['url']}")
        if item["excerpt"]:
            lines.append(f"- 摘要：{item['excerpt']}")
        lines.append("")

    out_md.write_text("\n".join(lines), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Export ahhhhfs inbox for local review")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--days", type=int, default=0, help="0=用 config 默认天数")
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    ahhhh = config.get("ahhhhfs", {})
    days = args.days or int(ahhhh.get("inbox_days", 30))
    db_path = ROOT / config["database"]["path"]
    site_db = Path(config["site"]["root"]).expanduser() / "data" / "site.db"
    out_json = ROOT / ahhhh.get("inbox_json", "data/ahhhhfs_inbox.json")
    out_md = ROOT / ahhhh.get("inbox_md", "data/ahhhhfs_inbox.md")

    payload = export_inbox(
        db_path=db_path,
        site_db=site_db,
        days=days,
        out_json=out_json,
        out_md=out_md,
    )
    print(
        f"inbox: {payload['total']} 篇，待挑选 {payload['pending_review']}，"
        f"已上站 {payload['on_site']}"
    )
    print(f"  JSON: {out_json}")
    print(f"  MD:   {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
