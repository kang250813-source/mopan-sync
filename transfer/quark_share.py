"""List folder branches inside public Quark share links."""

from __future__ import annotations

import re
import time
from functools import lru_cache

import httpx

SHARE_API = "https://drive-h.quark.cn"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

SHARE_ID_RE = re.compile(r"/s/([0-9a-fA-F]+)", re.IGNORECASE)
CLEAN_SUFFIX_RE = re.compile(r"[（(]点击保存立即查看[）)]")
LEADING_INDEX_RE = re.compile(r"^\d+-")

DEFAULT_DELAY = 0.35


def parse_share_id(url: str) -> str:
    match = SHARE_ID_RE.search(url)
    if not match:
        raise ValueError(f"无法解析分享 ID: {url}")
    return match.group(1)


def clean_branch_name(name: str) -> str:
    text = CLEAN_SUFFIX_RE.sub("", name or "").strip()
    while LEADING_INDEX_RE.match(text):
        text = LEADING_INDEX_RE.sub("", text, count=1)
    return text or name.strip()


def _list_dir(client: httpx.Client, *, share_id: str, stoken: str, pdir_fid: str) -> list[dict]:
    items: list[dict] = []
    page = 1
    while True:
        resp = client.get(
            f"{SHARE_API}/1/clouddrive/share/sharepage/detail",
            params={
                "pr": "ucpro",
                "fr": "pc",
                "pwd_id": share_id,
                "stoken": stoken,
                "pdir_fid": pdir_fid,
                "_page": str(page),
                "_size": "100",
                "_fetch_total": "1",
            },
        )
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(payload.get("message") or "列目录失败")
        batch = payload["data"]["list"]
        if not batch:
            break
        items.extend(batch)
        if len(items) >= payload["metadata"]["_total"]:
            break
        page += 1
    return items


def _share_token(client: httpx.Client, share_id: str) -> str:
    resp = client.post(
        f"{SHARE_API}/1/clouddrive/share/sharepage/token",
        params={"pr": "ucpro", "fr": "pc"},
        json={"pwd_id": share_id, "passcode": ""},
    )
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(payload.get("message") or "获取分享 token 失败")
    return payload["data"]["stoken"]


def list_folder_names(
    share_url: str,
    *,
    folder_fid: str | None = None,
    max_items: int = 40,
    delay: float = DEFAULT_DELAY,
) -> list[str]:
    """Return immediate subfolder names inside a Quark share (or subfolder)."""
    share_id = parse_share_id(share_url)
    headers = {"user-agent": USER_AGENT, "content-type": "application/json"}
    with httpx.Client(timeout=30.0, headers=headers) as client:
        stoken = _share_token(client, share_id)
        if delay:
            time.sleep(delay)

        start_fid = folder_fid or "0"
        items = _list_dir(client, share_id=share_id, stoken=stoken, pdir_fid=start_fid)
        folders = [item for item in items if item.get("file_type") == 0]

        if not folder_fid and len(folders) == 1:
            if delay:
                time.sleep(delay)
            items = _list_dir(client, share_id=share_id, stoken=stoken, pdir_fid=folders[0]["fid"])
            folders = [item for item in items if item.get("file_type") == 0]

        names: list[str] = []
        seen: set[str] = set()
        for folder in folders:
            raw = folder.get("file_name", "").strip()
            if not raw or raw.startswith("以上课件"):
                continue
            label = clean_branch_name(raw)
            if label in seen:
                continue
            seen.add(label)
            names.append(label)
            if len(names) >= max_items:
                break
        return names


def folder_fid_from_source_ref(source_ref: str | None) -> str | None:
    if not source_ref:
        return None
    parts = source_ref.strip("/").split("/")
    if len(parts) >= 4 and parts[0] == "k12" and parts[1] == "share":
        return parts[3]
    return None
