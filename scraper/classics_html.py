"""Convert classical txt to safe HTML for in-site reading."""

from __future__ import annotations

import html

DEFAULT_PREVIEW_CHARS = 800
DEFAULT_EXCERPT_CHARS = 160


def txt_to_content_html(text: str) -> str:
    body = html.escape(text.strip())
    return f'<pre class="classic-text">{body}</pre>'


def txt_preview_html(text: str, *, max_chars: int = DEFAULT_PREVIEW_CHARS) -> str:
    """Short in-site preview; full text lives on GitHub."""
    flat = text.strip()
    if len(flat) > max_chars:
        flat = flat[:max_chars].rstrip() + "…"
    body = html.escape(flat)
    return f'<pre class="classic-text classic-text--preview">{body}</pre>'


def txt_excerpt(text: str, limit: int = DEFAULT_EXCERPT_CHARS) -> str:
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[:limit] + "…"


def parse_wenyuange_ref(source_ref: str) -> tuple[str, str] | None:
    """wenyuange/{repo}/{rel/path.txt} -> (repo, rel)."""
    parts = source_ref.split("/", 2)
    if len(parts) != 3 or parts[0] != "wenyuange":
        return None
    return parts[1], parts[2]


def github_urls(
    source_ref: str,
    *,
    branch: str = "master",
    user: str = "wenyuange",
) -> dict[str, str] | None:
    parsed = parse_wenyuange_ref(source_ref)
    if not parsed:
        return None
    repo, rel = parsed
    base = f"https://github.com/{user}/{repo}"
    return {
        "blob": f"{base}/blob/{branch}/{rel}",
        "raw": f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/{rel}",
        "repo": base,
    }
