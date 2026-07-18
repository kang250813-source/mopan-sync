#!/usr/bin/env python3
"""Crawl LINUX DO category RSS (网盘资源) into local JSON."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import feedparser
import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from transfer.linuxdo_classify import classify_topic, pick_pan_password, pick_pan_url

DEFAULT_CATEGORY = "/c/resource/cloud-asset/94"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def load_config() -> dict:
    with (ROOT / "config.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def _linuxdo_cfg(config: dict | None = None) -> dict:
    cfg = (config or load_config()).get("linuxdo", {})
    return cfg if isinstance(cfg, dict) else {}


def _proxy_reachable(proxy: str, *, timeout: float = 1.5) -> bool:
    parsed = urlparse(proxy if "://" in proxy else f"http://{proxy}")
    host = parsed.hostname
    if not host:
        return False
    port = parsed.port
    if not port:
        port = 1080 if parsed.scheme.startswith("socks") else 7890
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _proxy_url(linuxdo: dict) -> str | None:
    use_proxy = str(linuxdo.get("use_proxy", "auto")).lower()
    if use_proxy in {"0", "false", "never", "off", "no"}:
        return None

    candidates: list[str] = []
    explicit = (linuxdo.get("proxy") or "").strip()
    if explicit:
        candidates.append(explicit)
    if use_proxy in {"auto", "true", "always", "on", "yes", "1", ""}:
        for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
            val = (os.environ.get(key) or "").strip()
            if val and val not in candidates:
                candidates.append(val)

    for proxy in candidates:
        if _proxy_reachable(proxy):
            return proxy
        print(f"  代理不可用，已跳过: {proxy}", flush=True)
    return None


def _load_cookie_header(linuxdo: dict) -> str:
    raw = (linuxdo.get("cookie") or os.environ.get("LINUXDO_COOKIE") or "").strip()
    if raw:
        return raw
    cookie_file = (linuxdo.get("cookie_file") or os.environ.get("LINUXDO_COOKIE_FILE") or "").strip()
    if not cookie_file:
        return ""
    path = Path(cookie_file).expanduser()
    if not path.is_file():
        return ""
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return ""
    if lines[0].lower().startswith("# netscape") or "\t" in lines[0]:
        parts: list[str] = []
        for line in lines:
            if line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) >= 7:
                parts.append(f"{cols[5]}={cols[6]}")
        return "; ".join(parts)
    return "; ".join(lines)


_PROXY_ENV_KEYS = (
    "http_proxy",
    "https_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
)


@contextmanager
def _without_proxy_env():
    saved = {k: os.environ.pop(k) for k in _PROXY_ENV_KEYS if k in os.environ}
    try:
        yield
    finally:
        os.environ.update(saved)


def _retry_wait(status: int, attempt: int) -> float:
    if status == 429:
        return min(60.0 * attempt, 180.0)
    return min(5.0 * attempt, 20.0)


def fetch_rss_http(url: str, *, config: dict | None = None) -> tuple[bytes, int, str]:
    """Fetch RSS bytes. Prefer curl_cffi (Cloudflare bypass), then httpx."""
    linuxdo = _linuxdo_cfg(config)
    headers = dict(DEFAULT_HEADERS)
    cookie = _load_cookie_header(linuxdo)
    if cookie:
        headers["Cookie"] = cookie
    proxy = _proxy_url(linuxdo)
    impersonate = (linuxdo.get("impersonate") or "chrome131").strip()
    timeout = float(linuxdo.get("timeout_seconds") or 45)
    retries = int(linuxdo.get("max_retries") or 6)
    last_error = ""
    saw_429 = False
    if proxy:
        print(f"  使用代理: {proxy}", flush=True)
    else:
        print("  未使用代理（直连 linux.do）", flush=True)

    for attempt in range(1, retries + 1):
        try:
            from curl_cffi import requests as cffi_requests

            kwargs: dict[str, Any] = {
                "headers": headers,
                "timeout": timeout,
                "impersonate": impersonate,
                "allow_redirects": True,
            }
            if proxy:
                kwargs["proxy"] = proxy
            ctx = nullcontext() if proxy else _without_proxy_env()
            with ctx:
                resp = cffi_requests.get(url, **kwargs)
            body = resp.content or b""
            ctype = (resp.headers.get("content-type") or "").lower()
            if resp.status_code == 200 and (
                b"<rss" in body[:4000] or b"<feed" in body[:4000] or "xml" in ctype
            ):
                return body, resp.status_code, "curl_cffi"
            last_error = f"curl_cffi status={resp.status_code} ctype={ctype[:40]}"
            if resp.status_code == 429:
                saw_429 = True
        except ImportError:
            last_error = "curl_cffi not installed"
            break
        except Exception as exc:  # noqa: BLE001
            last_error = f"curl_cffi {type(exc).__name__}: {exc}"

        if attempt < retries:
            wait = _retry_wait(429 if saw_429 else 0, attempt)
            print(f"  RSS 重试 {attempt}/{retries}（{last_error}），{wait:.0f}s 后重试…", flush=True)
            time.sleep(wait)

    if not saw_429:
        import httpx

        for attempt in range(1, retries + 1):
            try:
                with httpx.Client(
                    headers=headers,
                    timeout=timeout,
                    follow_redirects=True,
                    proxy=proxy,
                    trust_env=bool(proxy),
                ) as client:
                    resp = client.get(url)
                body = resp.content or b""
                ctype = (resp.headers.get("content-type") or "").lower()
                if resp.status_code == 200 and (
                    b"<rss" in body[:4000] or b"<feed" in body[:4000] or "xml" in ctype
                ):
                    return body, resp.status_code, "httpx"
                last_error = f"httpx status={resp.status_code} ctype={ctype[:40]}"
            except Exception as exc:  # noqa: BLE001
                last_error = f"httpx {type(exc).__name__}: {exc}"
            if attempt < retries:
                wait = _retry_wait(0, attempt)
                print(f"  RSS 重试 {attempt}/{retries}（{last_error}），{wait:.0f}s 后重试…", flush=True)
                time.sleep(wait)

    raise RuntimeError(f"RSS 请求失败：{last_error or 'unknown error'}")


def fetch_rss_page(base_url: str, page: int, *, config: dict | None = None) -> feedparser.FeedParserDict:
    url = base_url if page <= 1 else f"{base_url}?page={page}"
    body, status, via = fetch_rss_http(url, config=config)
    if page == 1:
        print(f"  RSS 获取成功 via {via} status={status}", flush=True)
    feed = feedparser.parse(body)
    feed.status = status
    return feed


def parse_published(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def min_published_from_days(max_age_days: int | None) -> datetime | None:
    if not max_age_days or max_age_days <= 0:
        return None
    return datetime.now(timezone.utc) - timedelta(days=max_age_days)


def topic_id_from_link(link: str) -> str | None:
    match = re.search(r"/topic/(\d+)", link or "")
    return match.group(1) if match else None


def parse_entry(entry: Any, *, require_pan: bool = False) -> dict | None:
    title = (entry.get("title") or "").strip()
    link = (entry.get("link") or "").strip()
    topic_id = topic_id_from_link(link)
    if not title or not topic_id:
        return None

    description = entry.get("summary") or entry.get("description") or ""
    pan = pick_pan_url(description)
    if not pan:
        if require_pan:
            return None
        pan_url, pan_type = "", ""
    else:
        pan_url, pan_type = pan
    pan_password = pick_pan_password(description) if pan_url else ""

    channel, category = classify_topic(title=title, description=description)
    published = entry.get("published") or entry.get("updated") or ""

    return {
        "topic_id": topic_id,
        "title": title,
        "link": link,
        "pan_url": pan_url,
        "pan_password": pan_password,
        "pan_type": pan_type,
        "channel": channel,
        "category": category,
        "eligible": bool(pan_url) and channel is not None,
        "published_at": published,
        "source_ref": f"linuxdo/94/{topic_id}",
        "crawled_at": datetime.now(timezone.utc).isoformat(),
    }


def crawl_category(
    *,
    rss_url: str,
    max_pages: int,
    delay: float,
    stop_on_dup: bool,
    require_pan: bool = False,
    retry_429: float = 60.0,
    min_published: datetime | None = None,
    config: dict | None = None,
) -> tuple[list[dict], dict[str, int]]:
    stats = {
        "pages": 0,
        "raw": 0,
        "parsed": 0,
        "eligible": 0,
        "skipped_no_pan": 0,
        "skipped_old": 0,
        "retries_429": 0,
    }
    seen_ids: set[str] = set()
    topics: list[dict] = []

    page = 1
    while True:
        if max_pages > 0 and page > max_pages:
            break

        feed = fetch_rss_page(rss_url, page, config=config)
        status = int(getattr(feed, "status", 0) or 0)
        entries = list(feed.entries or [])

        if status == 429:
            stats["retries_429"] += 1
            wait = retry_429 * min(stats["retries_429"], 5)
            print(f"  第 {page} 页 429，等待 {wait:.0f}s 后重试…")
            time.sleep(wait)
            continue

        stats["pages"] += 1
        stats["retries_429"] = 0

        if not entries:
            if page == 1:
                raise RuntimeError(f"RSS 解析失败 status={status}，未拿到任何条目")
            break

        new_count = 0
        page_dates: list[datetime] = []
        for entry in entries:
            stats["raw"] += 1
            published_raw = entry.get("published") or entry.get("updated") or ""
            published_dt = parse_published(published_raw)
            if published_dt:
                page_dates.append(published_dt)

            row = parse_entry(entry, require_pan=require_pan)
            if not row:
                stats["skipped_no_pan"] += 1
                continue
            stats["parsed"] += 1
            if min_published and published_dt and published_dt < min_published:
                stats["skipped_old"] += 1
                continue
            if not row["pan_url"]:
                stats["skipped_no_pan"] += 1
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
            f"累计 {len(topics)}（有链 {sum(1 for t in topics if t['pan_url'])}，"
            f"符合魔盘 {sum(1 for t in topics if t['eligible'])}，"
            f"跳过过旧 {stats['skipped_old']}）",
            flush=True,
        )

        if min_published and page_dates and min(page_dates) < min_published:
            print(
                f"  本页最早 {min(page_dates).date()}，早于下限 {min_published.date()}，停止翻页",
                flush=True,
            )
            break

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


def prune_topics_by_age(topics: list[dict], min_published: datetime | None) -> tuple[list[dict], int]:
    if not min_published:
        return topics, 0
    kept: list[dict] = []
    dropped = 0
    for row in topics:
        dt = parse_published(row.get("published_at") or "")
        if dt and dt < min_published:
            dropped += 1
            continue
        kept.append(row)
    return kept, dropped


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawl LINUX DO 网盘资源 RSS")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--pages", type=int, default=1, help="抓取 RSS 页数，0=直到无新帖")
    parser.add_argument("--delay", type=float, default=12.0, help="翻页间隔秒数（防 429）")
    parser.add_argument("--merge", action="store_true", help="与已有 JSON 合并去重")
    parser.add_argument(
        "--require-pan",
        action="store_true",
        help="仅保存含网盘链接的帖子（默认保存全部帖子）",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=0,
        help="只保留最近 N 天（0=读 config，负数=不限制）",
    )
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    linuxdo = config.get("linuxdo", {})
    rss_url = linuxdo.get("rss_url", f"https://linux.do{DEFAULT_CATEGORY}.rss")
    out_path = ROOT / linuxdo.get("data_path", "data/linuxdo_topics.json")
    max_age_days = args.max_age_days
    if max_age_days == 0:
        max_age_days = int(linuxdo.get("max_age_days", 730))
    min_published = min_published_from_days(max_age_days if max_age_days > 0 else None)

    print(f"抓取: {rss_url}")
    print(f"页数: {'全部' if args.pages == 0 else args.pages}，间隔 {args.delay}s")
    if min_published:
        print(f"时间范围: {min_published.date()} 至今（近 {max_age_days} 天）\n")
    else:
        print("时间范围: 不限制\n")

    topics, stats = crawl_category(
        rss_url=rss_url,
        max_pages=args.pages,
        delay=args.delay,
        stop_on_dup=args.pages == 0,
        require_pan=args.require_pan,
        min_published=min_published,
        config=config,
    )

    if args.merge and out_path.exists():
        old = json.loads(out_path.read_text(encoding="utf-8"))
        topics = merge_topics(old.get("topics", []), topics)

    topics, pruned = prune_topics_by_age(topics, min_published)
    if pruned:
        print(f"合并后剔除过旧 {pruned} 条")

    payload = {
        "source": "linux.do",
        "category": "网盘资源",
        "rss_url": rss_url,
        "max_age_days": max_age_days if max_age_days > 0 else None,
        "min_published_at": min_published.isoformat() if min_published else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
        "topics": topics,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    eligible = sum(1 for t in topics if t.get("eligible"))
    with_pan = sum(1 for t in topics if t.get("pan_url"))
    print(
        f"\n完成: 共 {len(topics)} 条，有网盘链 {with_pan}，符合魔盘 {eligible} 条"
        f"（解析跳过 {stats['skipped_no_pan']}，过旧跳过 {stats['skipped_old']}）"
    )
    print(f"输出: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
