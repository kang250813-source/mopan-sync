"""Extract resource links from article HTML."""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import urlparse

LINK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("quark", re.compile(r"https?://pan\.quark\.cn/s/[A-Za-z0-9_-]+")),
    (
        "baidu",
        re.compile(
            r"https?://pan\.baidu\.com/s/[A-Za-z0-9_-]+(?:\?pwd=[A-Za-z0-9]+)?"
        ),
    ),
    (
        "aliyun",
        re.compile(
            r"https?://(?:www\.)?(?:aliyundrive|alipan)\.com/s/[A-Za-z0-9_-]+"
        ),
    ),
    (
        "123pan",
        re.compile(r"https?://(?:www\.)?123pan\.com/s/[A-Za-z0-9_-]+(?:\.html)?"),
    ),
    (
        "lanzou",
        re.compile(r"https?://(?:[\w-]+\.)?lanzou[a-z]\.com/[A-Za-z0-9_-]+"),
    ),
    (
        "github",
        re.compile(r"https?://github\.com/[\w.-]+/[\w.-]+"),
    ),
    (
        "gitee",
        re.compile(r"https?://gitee\.com/[\w.-]+/[\w.-]+"),
    ),
]


def _clean_url(url: str) -> str:
    return url.rstrip(".,;)\"'")

def classify_url(url: str) -> str:
    for link_type, pattern in LINK_PATTERNS:
        if pattern.search(url):
            return link_type
    host = urlparse(url).netloc.lower()
    if host.endswith("ahhhhfs.com"):
        return "internal"
    return "other"


def extract_links(content_html: str) -> list[tuple[str, str]]:
    """Return deduplicated (link_type, url) pairs from HTML content."""
    text = unescape(content_html or "")
    found: list[tuple[str, str]] = []
    seen: set[str] = set()

    for link_type, pattern in LINK_PATTERNS:
        for match in pattern.findall(text):
            url = _clean_url(match)
            if url in seen:
                continue
            seen.add(url)
            found.append((link_type, url))

    # Generic href fallback for other external links
    for href in re.findall(r'href="(https?://[^"]+)"', text):
        url = _clean_url(href)
        if url in seen:
            continue
        link_type = classify_url(url)
        if link_type == "internal":
            continue
        seen.add(url)
        found.append((link_type, url))

    return found
