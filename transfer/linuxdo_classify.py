"""Classify LINUX DO 网盘资源 topics for mopan channels."""

from __future__ import annotations

import re

MEDIA_RE = re.compile(
    r"影视|电影|动漫|电视剧|美剧|韩剧|国漫|纪录片|综艺|番剧|"
    r"4K(?=.*(?:集|季|更|完结|HDR|杜比))|1080P|铂金珍藏版|官方正式版|"
    r"经典音乐|车载U盘|FLAC|\.wav|无损高音质|Orchester|Symphony",
    re.I,
)

SHORT_VIDEO_RE = re.compile(
    r"抖音|小红书|直播带货|绿幕|影视解说|短视频.*(?:运营|剪辑|起号)|半无人直播",
    re.I,
)

AI_RE = re.compile(
    r"AI|AIGC|人工智能|DeepSeek|ChatGPT|GPT|大模型|LLM|Midjourney|ComfyUI",
    re.I,
)

K12_RE = re.compile(
    r"英语|语法|新概念|年级|试卷|少儿|青少|K12|教辅|五三|"
    r"小学|中学|高考|考研|叶老师|雪梨|学习打卡|家庭教育课",
    re.I,
)

DISCOVER_RE = re.compile(
    r"软件|工具|APK|小程序|开源|项目|OpenStack|uniapp|"
    r"训练营|教程|课程|手册|配方|认知课",
    re.I,
)

EBOOK_RE = re.compile(r"电子书|小说合集|有声读物|杂志|2000册|书籍分享", re.I)

BUSINESS_RE = re.compile(r"创业|有术|商业|变现|群响|任推邦", re.I)


def pick_pan_url(description: str) -> tuple[str, str] | None:
    """Return (url, pan_type) preferring quark."""
    quark = re.findall(r"https://pan\.quark\.cn/s/[A-Za-z0-9]+", description)
    if quark:
        return quark[0].split("?")[0], "quark"
    baidu = re.findall(
        r"https://pan\.baidu\.com/s/[A-Za-z0-9_-]+(?:\?pwd=[A-Za-z0-9]+)?",
        description,
    )
    if baidu:
        return baidu[0].split("?")[0], "baidu"
    aliyun = re.findall(
        r"https://(?:www\.)?(?:aliyundrive|alipan)\.com/s/[A-Za-z0-9_-]+",
        description,
    )
    if aliyun:
        return aliyun[0].split("?")[0], "aliyun"
    return None


def classify_topic(*, title: str, description: str = "") -> tuple[str | None, str]:
    """Return (channel, category). channel=None means skip."""
    combined = f"{title}\n{description}"

    if MEDIA_RE.search(combined):
        return None, "影视音乐"
    if SHORT_VIDEO_RE.search(title):
        return None, "短视频运营"
    if EBOOK_RE.search(title) and not AI_RE.search(title):
        return None, "电子书"
    if BUSINESS_RE.search(title) and not AI_RE.search(title):
        return None, "创业商业"

    if AI_RE.search(title):
        return "ai_video", "AI学习"
    if K12_RE.search(title):
        return "k12", "K12教辅"
    if DISCOVER_RE.search(title):
        return "discover", "发现"

    return None, "其他"
