#!/usr/bin/env python3
"""Import items from a public Quark share link into mopan-site K12 channel."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SHARE_API = "https://drive-h.quark.cn"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def load_config() -> dict:
    with (ROOT / "config.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_share_id(url: str) -> str:
    match = re.search(r"/s/([0-9a-fA-F]+)", url)
    if not match:
        raise ValueError(f"无法解析分享 ID: {url}")
    return match.group(1)


def share_token(client: httpx.Client, share_id: str) -> tuple[str, str]:
    resp = client.post(
        f"{SHARE_API}/1/clouddrive/share/sharepage/token",
        params={"pr": "ucpro", "fr": "pc"},
        json={"pwd_id": share_id, "passcode": ""},
    )
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(f"获取分享 token 失败: {payload.get('message') or payload}")
    data = payload["data"]
    return data["stoken"], data.get("title") or "K12 资源"


def list_share_dir(
    client: httpx.Client,
    *,
    share_id: str,
    stoken: str,
    pdir_fid: str = "0",
) -> list[dict]:
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
                "_size": "50",
                "_fetch_total": "1",
            },
        )
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(f"列目录失败: {payload.get('message') or payload}")
        batch = payload["data"]["list"]
        if not batch:
            break
        items.extend(batch)
        if len(items) >= payload["metadata"]["_total"]:
            break
        page += 1
    return items


from transfer.quark_share import folder_fid_from_source_ref, list_folder_names


def normalize_title(name: str) -> str:
    title = name.strip()
    title = re.sub(r"[（(]点击保存立即查看[）)]", "", title).strip()
    if title.lower().startswith("python"):
        rest = title[6:].lstrip()
        return f"Python {rest}" if rest else "Python"
    if title.lower().startswith("scratch"):
        rest = title[7:].lstrip()
        return f"Scratch {rest}" if rest else "Scratch"
    return title


def attach_pan_branches(entries: list[dict], pan_url: str) -> None:
    cache: dict[tuple[str, str | None], list[str]] = {}
    for entry in entries:
        fid = folder_fid_from_source_ref(entry.get("source_ref"))
        key = (pan_url, fid)
        if key not in cache:
            try:
                cache[key] = list_folder_names(pan_url, folder_fid=fid)
            except Exception:
                cache[key] = []
        entry["pan_branches"] = cache[key]


def collect_entries(share_url: str) -> list[dict]:
    share_id = parse_share_id(share_url)
    headers = {"user-agent": USER_AGENT, "content-type": "application/json"}
    with httpx.Client(timeout=30.0, headers=headers) as client:
        stoken, share_title = share_token(client, share_id)
        root = list_share_dir(client, share_id=share_id, stoken=stoken)
        folders = [item for item in root if item.get("file_type") == 0]
        if not folders:
            return [
                {
                    "title": normalize_title(share_title),
                    "category": "少儿编程",
                    "excerpt": f"夸克网盘分享：{share_title}",
                    "source_ref": f"k12/share/{share_id}",
                }
            ]

        main = folders[0] if len(folders) == 1 else max(folders, key=lambda x: len(x.get("file_name", "")))
        children = list_share_dir(client, share_id=share_id, stoken=stoken, pdir_fid=main["fid"])
        subfolders = [item for item in children if item.get("file_type") == 0]

        entries: list[dict] = [
            {
                "title": normalize_title(share_title),
                "category": "少儿编程",
                "excerpt": "少儿编程全套课件合集，含机器人、Python、Scratch、C++ 等资料。",
                "source_ref": f"k12/share/{share_id}",
            }
        ]
        seen_titles: set[str] = set()
        for folder in subfolders:
            raw_name = folder.get("file_name", "").strip()
            if not raw_name or raw_name.startswith("以上课件"):
                continue
            child_count = len(list_share_dir(client, share_id=share_id, stoken=stoken, pdir_fid=folder["fid"]))
            if child_count == 0:
                continue
            title = normalize_title(raw_name)
            if title in seen_titles:
                title = f"{title}（补充）"
            seen_titles.add(title)
            entries.append(
                {
                    "title": title,
                    "category": "少儿编程",
                    "excerpt": f"{title}，共 {child_count} 项资料。打开网盘后进入对应文件夹查看。",
                    "source_ref": f"k12/share/{share_id}/{folder['fid']}",
                }
            )
        return entries


def main() -> int:
    parser = argparse.ArgumentParser(description="Import Quark share folders into K12 channel")
    parser.add_argument("share_url", help="Quark share URL, e.g. https://pan.quark.cn/s/xxx")
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_config()
    site_root = Path(config["site"]["root"]).expanduser()
    pan_url = args.share_url.split("#", 1)[0].strip()
    if "?" in pan_url:
        pan_url = pan_url.split("?", 1)[0]
    pan_type = config.get("pan", {}).get("type", "quark")
    published_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    entries = collect_entries(args.share_url)
    attach_pan_branches(entries, pan_url)
    print(f"准备导入 {len(entries)} 条到 K12 频道\n")

    if args.dry_run:
        for entry in entries:
            branches = entry.get("pan_branches") or []
            hint = f" · {len(branches)} 分支" if branches else ""
            print(f"- {entry['title']} ({entry['category']}){hint}")
        return 0

    sys.path.insert(0, str(site_root))
    from app.database import init_db, upsert_resource  # noqa: WPS433

    init_db(site_root / "data" / "site.db")
    stats = {"inserted": 0, "updated": 0}
    for entry in entries:
        result = upsert_resource(
            title=entry["title"],
            pan_url=pan_url,
            pan_type=pan_type,
            category=entry["category"],
            excerpt=entry["excerpt"],
            published_at=published_at,
            link_status="own",
            channel="k12",
            source_ref=entry["source_ref"],
            pan_branches=entry.get("pan_branches"),
        )
        stats[result] += 1
        print(f"  {result}: {entry['title']}")

    port = config["site"].get("port", 8083)
    print(f"\n完成 inserted={stats['inserted']} updated={stats['updated']}")
    print(f"K12 频道: http://localhost:{port}/?channel=k12")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
