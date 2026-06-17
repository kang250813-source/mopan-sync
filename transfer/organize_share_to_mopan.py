#!/usr/bin/env python3
"""Organize /来自：分享 into /魔盘/* and import eligible items to mopan-site."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from transfer.quark_client import QuarkClient, QuarkError, load_cookie_from_qas

SHARE_SOURCE = "/来自：分享"
MOPAN_ROOT = "/魔盘"

BUCKETS = {
    "discover": "01-发现-软件工具",
    "k12": "02-K12-教辅",
    "ai": "03-AI学习-课程",
    "short_video": "04-短视频-运营",
    "ebook": "05-电子书-有声",
    "media": "06-影视-音乐",
    "business": "07-创业-商业",
    "other": "99-待删或自用",
}

CHANNEL_BY_BUCKET = {
    "discover": "discover",
    "k12": "k12",
    "ai": "ai_video",
}

EXTRA_ROOT_MOVES = [
    ("/最新1-9年级辅导资料集合", "k12", "K12教辅", True),
    ("/雪梨老师25套小学英语王炸学习资料", "k12", "K12教辅", False),  # 与分享夹内雪梨重复
]

GRADE4_DUP_RE = re.compile(r"四年级.*(试卷|真题|测试卷)", re.I)


@dataclass
class ItemPlan:
    fid: str
    name: str
    file_type: int
    bucket: str
    category: str
    on_site: bool
    channel: str | None = None


def load_config() -> dict:
    with (ROOT / "config.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def classify(name: str, file_type: int) -> tuple[str, str, bool]:
    """Return (bucket_key, category, on_site)."""
    if GRADE4_DUP_RE.search(name) or (
        "四年级" in name and name.lower().endswith(".pdf")
    ):
        return "k12", "教辅试卷", False

    if any(
        k in name
        for k in [
            "五三",
            "五年高考",
            "雪梨老师",
            "【L系列】",
            "学习打卡表",
            "DeepSeek中小学生",
            "逢考必过",
            "少儿动画课",
            "学霸高效阅读",
            "乐理入门",
            "1-9年级",
            "辅导资料",
        ]
    ):
        return "k12", "K12教辅", True

    if any(
        k in name
        for k in [
            "SadTalker",
            "Lossless Zoomer",
            "Framepack",
            "ChatGPT",
            "chatgpt",
            "AIGC",
            "AI实操",
            "AI课程",
            "AI数字人",
            "AI无损",
            "AI短视频",
            "AI工人工",
            "从零进阶AI",
            "怎样用AI",
            "deepseek",
            "DeepSeek",
            "🤖",
            "韩超·AI",
            "马馺",
            "黄豆奶爸",
        ]
    ) or name.startswith("AI") or "AI" in name[:6]:
        return "ai", "AI学习", True

    if any(k in name for k in ["秒看电视", "自动精灵", "鱼皮项目"]) or name.lower().endswith(
        ".apk"
    ):
        return "discover", "软件工具", True

    if any(
        k in name
        for k in [
            "抖音",
            "小红书",
            "直播",
            "绿幕",
            "影视解说",
            "视频剪辑",
            "国际抖音",
            "企业号",
            "企业抖音",
        ]
    ):
        return "short_video", "短视频运营", False

    if any(
        k in name
        for k in ["书籍", "图书", "小说", "有声读物", "New Yorker", "纽约客"]
    ):
        return "ebook", "电子书", False

    if any(
        k in name
        for k in [
            "电视剧",
            "黑镜",
            "斗罗大陆",
            "第八日的蝉",
            "经典音乐",
            "Mahler",
            "FLAC",
            ".wav",
            "电影版",
            "Orchester",
        ]
    ):
        return "media", "影视音乐", False

    if any(
        k in name
        for k in [
            "创业",
            "有术",
            "认知",
            "洞悉真相",
            "父母与孩子",
            "美食实体",
            "50条关键",
        ]
    ):
        return "business", "创业商业", False

    return "other", "其他", False


def plan_items(client: QuarkClient) -> list[ItemPlan]:
    share_fid = client.get_fid_by_path(SHARE_SOURCE)
    if not share_fid:
        raise QuarkError(f"找不到目录: {SHARE_SOURCE}")

    plans: list[ItemPlan] = []
    for item in client.list_dir(share_fid):
        name = (item.get("file_name") or "").strip()
        if not name:
            continue
        bucket, category, on_site = classify(name, int(item.get("file_type", 1)))
        channel = CHANNEL_BY_BUCKET.get(bucket) if on_site else None
        plans.append(
            ItemPlan(
                fid=item["fid"],
                name=name,
                file_type=int(item.get("file_type", 1)),
                bucket=bucket,
                category=category,
                on_site=on_site,
                channel=channel,
            )
        )
    return plans


def plan_extra_roots(client: QuarkClient) -> list[ItemPlan]:
    plans: list[ItemPlan] = []
    for path, bucket, category, on_site in EXTRA_ROOT_MOVES:
        fid = client.get_fid_by_path(path)
        if not fid:
            continue
        name = path.rsplit("/", 1)[-1]
        channel = CHANNEL_BY_BUCKET.get(bucket) if on_site else None
        plans.append(
            ItemPlan(
                fid=fid,
                name=name,
                file_type=0,
                bucket=bucket,
                category=category,
                on_site=on_site,
                channel=channel,
            )
        )
    return plans


def ensure_buckets(client: QuarkClient) -> dict[str, str]:
    client.ensure_folder_path(MOPAN_ROOT.strip("/"))
    fids: dict[str, str] = {}
    mopan_fid = client.get_fid_by_path(MOPAN_ROOT)
    if not mopan_fid:
        mopan_fid = client.ensure_folder_path(MOPAN_ROOT.strip("/"))
    for key, folder_name in BUCKETS.items():
        target_path = f"{MOPAN_ROOT}/{folder_name}"
        fids[key] = client.ensure_folder_path(target_path.strip("/"))
    return fids


def import_to_site(
    *,
    site_root: Path,
    title: str,
    pan_url: str,
    channel: str,
    category: str,
    source_ref: str,
) -> str:
    sys.path.insert(0, str(site_root))
    from app.database import init_db, upsert_resource  # noqa: WPS433

    init_db(site_root / "data" / "site.db")
    excerpt = f"来自小怪主盘{MOPAN_ROOT}整理，打开网盘查看完整资料。"
    return upsert_resource(
        title=title,
        pan_url=pan_url,
        pan_type="quark",
        category=category,
        excerpt=excerpt,
        published_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        link_status="own",
        channel=channel,
        source_ref=source_ref,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Organize 来自：分享 into 魔盘")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不移动不导入")
    parser.add_argument("--skip-move", action="store_true", help="跳过网盘移动")
    parser.add_argument("--skip-import", action="store_true", help="跳过站点导入")
    parser.add_argument("--delay", type=float, default=1.2, help="分享链创建间隔秒数")
    args = parser.parse_args()

    config = load_config()
    qas_path = Path(config["pan"]["qas_config"]).expanduser()
    site_root = Path(config["site"]["root"]).expanduser()
    manifest_path = ROOT / "data" / "share_organize_manifest.json"

    cookie = load_cookie_from_qas(qas_path)
    client = QuarkClient(cookie)
    account = client.get_account_info()
    print(f"账号: {account.get('nickname') or account.get('mobile') or 'OK'}")

    share_plans = plan_items(client)
    extra_plans = plan_extra_roots(client)
    all_plans = share_plans + extra_plans

    on_site_count = sum(1 for p in all_plans if p.on_site)
    print(f"\n计划整理 {len(all_plans)} 项（分享夹 {len(share_plans)} + 根目录补充 {len(extra_plans)}）")
    print(f"符合魔盘站上架: {on_site_count} 项\n")

    by_bucket: dict[str, list[ItemPlan]] = {k: [] for k in BUCKETS}
    for plan in all_plans:
        by_bucket[plan.bucket].append(plan)

    for key, items in by_bucket.items():
        if not items:
            continue
        site_n = sum(1 for i in items if i.on_site)
        print(f"  {BUCKETS[key]}: {len(items)} 项（上站 {site_n}）")
        for item in items:
            flag = "✓站" if item.on_site else "网盘"
            print(f"    [{flag}] {item.name}")

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "account": account.get("nickname"),
        "buckets": BUCKETS,
        "items": [
            {
                "fid": p.fid,
                "name": p.name,
                "bucket": p.bucket,
                "bucket_path": f"{MOPAN_ROOT}/{BUCKETS[p.bucket]}",
                "category": p.category,
                "on_site": p.on_site,
                "channel": p.channel,
            }
            for p in all_plans
        ],
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n清单已保存: {manifest_path}")

    if args.dry_run:
        print("\n[dry-run] 未执行移动与导入")
        return 0

    bucket_fids: dict[str, str] = {}
    if not args.skip_move:
        print("\n== 创建 /魔盘 目录结构 ==")
        bucket_fids = ensure_buckets(client)
        print(f"  /魔盘 就绪，子目录 {len(bucket_fids)} 个")

        print("\n== 移动文件 ==")
        moved = 0
        for plan in all_plans:
            dest = bucket_fids[plan.bucket]
            print(f"  → {BUCKETS[plan.bucket]}: {plan.name}")
            client.move_files([plan.fid], dest)
            moved += 1
        print(f"  完成移动 {moved} 项")
    else:
        bucket_fids = ensure_buckets(client)

    if args.skip_import:
        print("\n跳过站点导入")
        return 0

    print("\n== 导入魔盘站（仅符合项）==")
    share_cache_path = ROOT / config["quark"].get("share_cache_path", "data/mopan_share_links.json")
    cache: dict[str, str] = {}
    if share_cache_path.exists():
        cache = json.loads(share_cache_path.read_text(encoding="utf-8"))

    stats = {"inserted": 0, "updated": 0, "failed": 0, "skipped": 0}
    for plan in all_plans:
        if not plan.on_site or not plan.channel:
            stats["skipped"] += 1
            continue
        cache_key = f"mopan/{plan.bucket}/{plan.fid}"
        try:
            if cache_key in cache:
                pan_url = cache[cache_key]
                print(f"  缓存: {plan.name}")
            else:
                pan_url = client.create_share_link(plan.fid, plan.name[:80])
                cache[cache_key] = pan_url
                print(f"  分享: {plan.name} → {pan_url}")
                time.sleep(args.delay)

            result = import_to_site(
                site_root=site_root,
                title=plan.name,
                pan_url=pan_url,
                channel=plan.channel,
                category=plan.category,
                source_ref=f"share_organize/{plan.bucket}/{plan.fid}",
            )
            stats[result] += 1
        except Exception as exc:
            stats["failed"] += 1
            print(f"  失败: {plan.name} — {exc}")

    share_cache_path.parent.mkdir(parents=True, exist_ok=True)
    share_cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"\n完成: inserted={stats['inserted']} updated={stats['updated']} "
        f"failed={stats['failed']} skipped={stats['skipped']}"
    )
    port = config["site"].get("port", 8083)
    print(f"魔盘预览: http://127.0.0.1:{port}/")
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
