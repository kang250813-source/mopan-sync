#!/usr/bin/env python3
"""Crawl LINUX DO category RSS (网盘资源) into local JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import feedparser
import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from transfer.linuxdo_classify import classify_topic, pick_pan_url

DEFAULT_CATEGORY = "/c/resource/cloud-asset/94"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def load_config() -> dict:
    with (ROOT / "config.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def topic_id_from_link(link: str) -> str | None:
    match = re.search(r"/topic/(\d+)", link or "")
    return match.group(1) if match else None


def parse_entry(entry: Any) -> dict | None:
    title = (entry.get("title") or "").strip()
    link = (entry.get("link") or "").strip()
    topic_id = topic_id_from_link(link)
    if not title or not topic_id:
        return None

    description = entry.get("summary") or entry.get("description") or ""
    pan = pick_pan_url(description)
    if not pan:
        return None
    pan_url, pan_type = pan

    channel, category = classify_topic(title=title, description=description)
    published = entry.get("published") or entry.get("updated") or ""

    return {
        "topic_id": topic_id,
        "title": title,
        "link": link,
        "pan_url": pan_url,
        "pan_type": pan_type,
        "channel": channel,
        "category": category,
        "eligible": channel is not None,
        "published_at": published,
        "source_ref": f"linuxdo/94/{topic_id}",
        "crawled_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_rss_page(base_url: str, page: int) -> feedparser.FeedParserDict:
    url = base_url if page <= 1 else f"{base_url}?page={page}"
    return feedparser.parse(url, agent=USER_AGENT)


def crawl_category(
    *,
    rss_url: str,
    max_pages: int,
    delay: float,
    stop_on_dup: bool,
) -> tuple[list[dict], dict[str, int]]:
    stats = {"pages": 0, "raw": 0, "parsed": 0, "eligible": 0, "skipped_no_pan": 0}
    seen_ids: set[str] = set()
    topics: list[dict] = []

    page = 1
    while True:
        if max_pages > 0 and page > max_pages:
            break

        feed = fetch_rss_page(rss_url, page)
        status = int(getattr(feed, "status", 0) or 0)
        entries = list(feed.entries or [])
        stats["pages"] += 1

        if status == 429 or not entries:
            if page == 1:
                raise RuntimeError(f"RSS 请求失败 status={status}，请稍后重试")
            break

        new_count = 0
        for entry in entries:
            stats["raw"] += 1
            row = parse_entry(entry)
            if not row:
                stats["skipped_no_pan"] += 1
                continue
            stats["parsed"] += 1
            if row["eligible"]:
                stats["eligible"] += 1
            tid = row["topic_id"]
            if tid in seen_ids:
                continue
            seen_ids.add(tid)
            topics.append(row)
            new_count += 1

        print(
            f"  第 {page} 页: {len(entries)} 条, 新增 {new_count}, "
            f"累计 {len(topics)}（符合 {sum(1 for t in topics if t['eligible'])}）"
        )

        if new_count == 0 and stop_on_dup:
            break
        if len(entries) < 25:
            break

        page += 1
        if delay > 0:
            time.sleep(delay)

    return topics, stats


def merge_topics(existing: list[dict], fresh: list[dict]) -> list[dict]:
    by_id = {t["topic_id"]: t for t in existing}
    for row in fresh:
        by_id[row["topic_id"]] = row
    merged = list(by_id.values())
    merged.sort(key=lambda t: int(t["topic_id"]), reverse=True)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl LINUX DO 网盘资源 RSS")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--pages", type=int, default=1, help="抓取 RSS 页数，0=直到重复")
    parser.add_argument("--delay", type=float, default=12.0, help="翻页间隔秒数（防 429）")
    parser.add_argument("--merge", action="store_true", help="与已有 JSON 合并去重")
    args = parser.parse_args()

    config = load_config()
    linuxdo = config.get("linuxdo", {})
    rss_url = linuxdo.get("rss_url", f"https://linux.do{DEFAULT_CATEGORY}.rss")
    out_path = ROOT / linuxdo.get("data_path", "data/linuxdo_topics.json")

    print(f"抓取: {rss_url}")
    print(f"页数: {'全部' if args.pages == 0 else args.pages}，间隔 {args.delay}s\n")

    topics, stats = crawl_category(
        rss_url=rss_url,
        max_pages=args.pages,
        delay=args.delay,
        stop_on_dup=args.pages == 0,
    )

    if args.merge and out_path.exists():
        old = json.loads(out_path.read_text(encoding="utf-8"))
        topics = merge_topics(old.get("topics", []), topics)

    payload = {
        "source": "linux.do",
        "category": "网盘资源",
        "rss_url": rss_url,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
        "topics": topics,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    eligible = sum(1 for t in topics if t.get("eligible"))
    print(
        f"\n完成: 共 {len(topics)} 条，符合魔盘 {eligible} 条"
        f"（无网盘链 {stats['skipped_no_pan']}）"
    )
    print(f"输出: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
