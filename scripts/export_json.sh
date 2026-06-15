#!/usr/bin/env bash
# 导出 SQLite 为 JSON，方便本地查看/后续导入魔盘站点
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT="${1:-data/ahhhhfs_export.json}"
export MOPAN_EXPORT_OUT="$OUT"
.venv/bin/python << 'PY'
import json, os, sqlite3
from pathlib import Path

root = Path(".")
db_path = root / "data/ahhhhfs.db"
out_path = Path(os.environ.get("MOPAN_EXPORT_OUT", "data/ahhhhfs_export.json"))

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

categories = {
    row["wp_id"]: {"name": row["name"], "slug": row["slug"]}
    for row in conn.execute("SELECT wp_id, name, slug FROM categories")
}

articles = []
for row in conn.execute(
    "SELECT * FROM articles ORDER BY published_at DESC"
):
    item = dict(row)
    cat_ids = json.loads(item.pop("categories_json") or "[]")
    item["categories"] = [categories.get(cid, {"id": cid}) for cid in cat_ids]
    item["tags"] = json.loads(item.pop("tags_json") or "[]")
    links = conn.execute(
        "SELECT link_type, url FROM links WHERE article_wp_id = ? ORDER BY id",
        (row["wp_id"],),
    ).fetchall()
    item["links"] = [{"type": l["link_type"], "url": l["url"]} for l in links]
    articles.append(item)

payload = {
    "source": "ahhhhfs.com",
    "exported_at": __import__("datetime").datetime.now().isoformat(),
    "count": len(articles),
    "articles": articles,
}

out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"exported {len(articles)} articles -> {out_path}")
PY
