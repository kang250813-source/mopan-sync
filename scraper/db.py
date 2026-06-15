"""SQLite storage for scraped ahhhhfs articles."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  wp_id INTEGER NOT NULL UNIQUE,
  slug TEXT,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  excerpt TEXT,
  content_html TEXT,
  published_at TEXT,
  modified_at TEXT,
  categories_json TEXT,
  tags_json TEXT,
  featured_image TEXT,
  scraped_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at DESC);

CREATE TABLE IF NOT EXISTS links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  article_wp_id INTEGER NOT NULL,
  link_type TEXT NOT NULL,
  url TEXT NOT NULL,
  UNIQUE(article_wp_id, url),
  FOREIGN KEY (article_wp_id) REFERENCES articles(wp_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_links_type ON links(link_type);
CREATE INDEX IF NOT EXISTS idx_links_article ON links(article_wp_id);

CREATE TABLE IF NOT EXISTS categories (
  wp_id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT,
  count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS transfer_queue (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  article_wp_id INTEGER NOT NULL,
  title TEXT NOT NULL,
  source_quark_url TEXT NOT NULL UNIQUE,
  source_article_url TEXT,
  category TEXT,
  excerpt TEXT,
  published_at TEXT,
  quark_save_path TEXT,
  mopan_quark_url TEXT,
  transfer_status TEXT NOT NULL DEFAULT 'pending',
  transfer_error TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_transfer_status ON transfer_queue(transfer_status);
CREATE INDEX IF NOT EXISTS idx_transfer_article ON transfer_queue(article_wp_id);
"""


@dataclass
class Article:
    wp_id: int
    title: str
    url: str
    slug: str | None = None
    excerpt: str | None = None
    content_html: str | None = None
    published_at: str | None = None
    modified_at: str | None = None
    categories: list[int] = field(default_factory=list)
    tags: list[int] = field(default_factory=list)
    featured_image: str | None = None
    links: list[tuple[str, str]] = field(default_factory=list)


class ArticleDB:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert_categories(self, categories: list[dict]) -> None:
        with self._connect() as conn:
            for cat in categories:
                conn.execute(
                    """
                    INSERT INTO categories (wp_id, name, slug, count)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(wp_id) DO UPDATE SET
                      name = excluded.name,
                      slug = excluded.slug,
                      count = excluded.count
                    """,
                    (
                        cat["id"],
                        cat["name"],
                        cat.get("slug"),
                        cat.get("count", 0),
                    ),
                )

    def upsert_article(self, article: Article) -> bool:
        """Insert or update. Returns True if newly inserted."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM articles WHERE wp_id = ?",
                (article.wp_id,),
            ).fetchone()

            conn.execute(
                """
                INSERT INTO articles (
                  wp_id, slug, title, url, excerpt, content_html,
                  published_at, modified_at, categories_json, tags_json,
                  featured_image, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(wp_id) DO UPDATE SET
                  slug = excluded.slug,
                  title = excluded.title,
                  url = excluded.url,
                  excerpt = excluded.excerpt,
                  content_html = excluded.content_html,
                  published_at = excluded.published_at,
                  modified_at = excluded.modified_at,
                  categories_json = excluded.categories_json,
                  tags_json = excluded.tags_json,
                  featured_image = excluded.featured_image,
                  scraped_at = excluded.scraped_at
                """,
                (
                    article.wp_id,
                    article.slug,
                    article.title,
                    article.url,
                    article.excerpt,
                    article.content_html,
                    article.published_at,
                    article.modified_at,
                    json.dumps(article.categories, ensure_ascii=False),
                    json.dumps(article.tags, ensure_ascii=False),
                    article.featured_image,
                    now,
                ),
            )

            conn.execute(
                "DELETE FROM links WHERE article_wp_id = ?",
                (article.wp_id,),
            )
            for link_type, url in article.links:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO links (article_wp_id, link_type, url)
                    VALUES (?, ?, ?)
                    """,
                    (article.wp_id, link_type, url),
                )

            return existing is None

    def total_articles(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM articles").fetchone()
            return int(row["c"])

    def link_stats(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT link_type, COUNT(*) AS c
                FROM links
                GROUP BY link_type
                ORDER BY c DESC
                """
            ).fetchall()
            return {row["link_type"]: int(row["c"]) for row in rows}

    def articles_with_pan_links(self) -> int:
        pan_types = ("quark", "baidu", "aliyun", "123pan", "lanzou")
        placeholders = ",".join("?" for _ in pan_types)
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT COUNT(DISTINCT article_wp_id) AS c
                FROM links
                WHERE link_type IN ({placeholders})
                """,
                pan_types,
            ).fetchone()
            return int(row["c"])

    def build_transfer_queue(self, save_path_prefix: str = "/魔盘") -> dict[str, int]:
        """Populate transfer_queue from articles that have quark links."""
        now = datetime.now(timezone.utc).isoformat()
        stats = {"candidates": 0, "inserted": 0, "skipped": 0}
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT a.wp_id, a.title, a.url, a.excerpt, a.published_at,
                       a.categories_json, l.url AS quark_url
                FROM articles a
                JOIN links l ON l.article_wp_id = a.wp_id AND l.link_type = 'quark'
                ORDER BY a.published_at DESC, a.wp_id DESC
                """
            ).fetchall()
            stats["candidates"] = len(rows)
            for row in rows:
                base_url = row["quark_url"].split("#", 1)[0].split("?", 1)[0].strip()
                exists = conn.execute(
                    "SELECT id FROM transfer_queue WHERE source_quark_url = ?",
                    (base_url,),
                ).fetchone()
                if exists:
                    stats["skipped"] += 1
                    continue

                category = self._primary_category(conn, row["categories_json"])
                month = (row["published_at"] or "unknown")[:7]
                safe_title = row["title"].replace("/", "-").strip()[:120]
                save_path = f"{save_path_prefix.rstrip('/')}/{month}/{safe_title}"

                conn.execute(
                    """
                    INSERT INTO transfer_queue (
                      article_wp_id, title, source_quark_url, source_article_url,
                      category, excerpt, published_at, quark_save_path,
                      transfer_status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        row["wp_id"],
                        row["title"],
                        base_url,
                        row["url"],
                        category,
                        row["excerpt"],
                        row["published_at"],
                        save_path,
                        now,
                        now,
                    ),
                )
                stats["inserted"] += 1
        return stats

    def _primary_category(
        self, conn: sqlite3.Connection, categories_json: str | None
    ) -> str:
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

    def get_transfer_pending(self, limit: int | None = None) -> list[sqlite3.Row]:
        with self._connect() as conn:
            sql = """
                SELECT * FROM transfer_queue
                WHERE transfer_status = 'pending'
                ORDER BY published_at DESC, id DESC
            """
            if limit:
                sql += f" LIMIT {int(limit)}"
            return conn.execute(sql).fetchall()

    def get_transfer_queued(self, limit: int | None = None) -> list[sqlite3.Row]:
        with self._connect() as conn:
            sql = """
                SELECT * FROM transfer_queue
                WHERE transfer_status IN ('queued', 'done')
                ORDER BY published_at DESC, id DESC
            """
            if limit:
                sql += f" LIMIT {int(limit)}"
            return conn.execute(sql).fetchall()

    def mark_transfer_status(
        self,
        ids: list[int],
        status: str,
        *,
        error: str | None = None,
        mopan_quark_url: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            for item_id in ids:
                conn.execute(
                    """
                    UPDATE transfer_queue
                    SET transfer_status = ?, transfer_error = ?,
                        mopan_quark_url = COALESCE(?, mopan_quark_url),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (status, error, mopan_quark_url, now, item_id),
                )

    def transfer_stats(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT transfer_status, COUNT(*) AS c
                FROM transfer_queue
                GROUP BY transfer_status
                """
            ).fetchall()
            return {row["transfer_status"]: int(row["c"]) for row in rows}

    def total_transfer_queue(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM transfer_queue").fetchone()
            return int(row["c"])
