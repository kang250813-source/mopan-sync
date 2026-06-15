"""Crawl ahhhhfs.com via WordPress REST API."""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path

import yaml

from scraper.db import Article, ArticleDB
from scraper.extract_links import extract_links

ROOT = Path(__file__).resolve().parent.parent


def load_config(config_path: Path) -> dict:
    with config_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _strip_html(html: str | None) -> str | None:
    if not html:
        return None
    text = unescape(html)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _request_json(url: str, user_agent: str, max_retries: int) -> tuple[object, dict[str, str]]:
    headers = {"User-Agent": user_agent, "Accept": "application/json"}
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                hdrs = {k.lower(): v for k, v in resp.headers.items()}
                return json.loads(body), hdrs
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code in (429, 403, 500, 502, 503, 504) and attempt < max_retries:
                time.sleep(2.0 * attempt)
                continue
            raise
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt < max_retries:
                time.sleep(2.0 * attempt)
                continue
            raise

    raise RuntimeError(f"request failed: {url}") from last_error


def fetch_categories(api_base: str, cfg: dict) -> list[dict]:
    url = f"{api_base.rstrip('/')}/categories?per_page=100"
    data, _ = _request_json(
        url,
        cfg["user_agent"],
        int(cfg.get("max_retries", 5)),
    )
    return data  # type: ignore[return-value]


def fetch_posts_page(
    api_base: str,
    cfg: dict,
    *,
    page: int,
    after: str,
) -> tuple[list[dict], int, int]:
    params = {
        "per_page": str(cfg.get("per_page", 100)),
        "page": str(page),
        "after": after,
    }
    url = f"{api_base.rstrip('/')}/posts?{urllib.parse.urlencode(params)}"
    data, hdrs = _request_json(
        url,
        cfg["user_agent"],
        int(cfg.get("max_retries", 5)),
    )
    total = int(hdrs.get("x-wp-total", "0"))
    total_pages = int(hdrs.get("x-wp-totalpages", "1"))
    return data, total, total_pages  # type: ignore[return-value]


def post_to_article(post: dict) -> Article:
    title = unescape(post.get("title", {}).get("rendered", "")).strip()
    excerpt_html = post.get("excerpt", {}).get("rendered")
    content_html = post.get("content", {}).get("rendered")
    links = extract_links(content_html or "")

    return Article(
        wp_id=int(post["id"]),
        slug=post.get("slug"),
        title=title,
        url=post.get("link", ""),
        excerpt=_strip_html(excerpt_html),
        content_html=content_html,
        published_at=post.get("date"),
        modified_at=post.get("modified"),
        categories=list(post.get("categories") or []),
        tags=list(post.get("tags") or []),
        featured_image=post.get("jetpack_featured_media_url"),
        links=links,
    )


def crawl_ahhhhfs(config_path: Path, *, after: str | None = None) -> dict[str, int]:
    config = load_config(config_path)
    source = config["source"]
    db = ArticleDB(ROOT / config["database"]["path"])

    api_base = source["api_base"]
    delay = float(source.get("request_delay_seconds", 1.2))
    after_date = after or source.get("after", "2025-06-14T00:00:00")

    print(f"[mopan-sync] source: {source['name']}")
    print(f"[mopan-sync] after:  {after_date}")

    categories = fetch_categories(api_base, source)
    db.upsert_categories(categories)
    print(f"[mopan-sync] categories cached: {len(categories)}")

    stats = {
        "pages": 0,
        "fetched": 0,
        "inserted": 0,
        "updated": 0,
        "errors": 0,
    }

    page = 1
    total_pages = 1
    total_expected = 0

    while page <= total_pages:
        try:
            posts, total, total_pages = fetch_posts_page(
                api_base,
                source,
                page=page,
                after=after_date,
            )
        except Exception as exc:
            print(f"[error] page {page}: {exc}", file=sys.stderr)
            stats["errors"] += 1
            page += 1
            time.sleep(delay * 2)
            continue

        if page == 1:
            total_expected = total
            print(f"[mopan-sync] total posts to fetch: {total} ({total_pages} pages)")

        stats["pages"] += 1
        print(f"[mopan-sync] page {page}/{total_pages} — {len(posts)} posts")

        for post in posts:
            article = post_to_article(post)
            inserted = db.upsert_article(article)
            stats["fetched"] += 1
            if inserted:
                stats["inserted"] += 1
            else:
                stats["updated"] += 1

        page += 1
        if page <= total_pages:
            time.sleep(delay)

    stats["total_in_db"] = db.total_articles()
    stats["expected"] = total_expected
    stats["link_stats"] = db.link_stats()
    stats["articles_with_pan_links"] = db.articles_with_pan_links()
    return stats


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Crawl ahhhhfs.com articles via WP REST API")
    parser.add_argument(
        "--config",
        default=str(ROOT / "config.yaml"),
        help="Path to config.yaml",
    )
    parser.add_argument(
        "--after",
        default=None,
        help="ISO date lower bound, e.g. 2025-06-14T00:00:00",
    )
    args = parser.parse_args()

    stats = crawl_ahhhhfs(Path(args.config), after=args.after)

    print("\n--- crawl summary ---")
    for key in ("expected", "fetched", "inserted", "updated", "pages", "errors", "total_in_db", "articles_with_pan_links"):
        if key in stats:
            print(f"  {key}: {stats[key]}")
    print("  link_stats:")
    for link_type, count in stats.get("link_stats", {}).items():
        print(f"    {link_type}: {count}")


if __name__ == "__main__":
    main()
