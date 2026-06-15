"""Sanitize scraped HTML for hosting on mopan-site."""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import urlparse

_AHHHHFS = re.compile(r"https?://(?:www\.)?ahhhhfs\.com[^\s\"'<>]*", re.I)
_A_TAG = re.compile(
    r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
    re.I | re.DOTALL,
)
_SCRIPT_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.DOTALL)
_AFFILIATE_HINT = re.compile(
    r"(aff\.php|aff=|register\?aff=|promo|优惠码|affiliate)",
    re.I,
)


def _strip_tag(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).strip()


def sanitize_content_html(html: str | None) -> str | None:
    if not html:
        return None
    text = unescape(html)
    text = _SCRIPT_STYLE.sub("", text)

    def replace_anchor(match: re.Match[str]) -> str:
        href = match.group(1)
        inner = match.group(2)
        label = _strip_tag(inner) or href
        host = urlparse(href).netloc.lower()
        if "ahhhhfs.com" in host:
            return label
        if _AFFILIATE_HINT.search(href):
            return label
        return match.group(0)

    text = _A_TAG.sub(replace_anchor, text)
    text = _AHHHHFS.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or None
