# 魔盘 · 本地同步（mopan-sync）

从 **ahhhhfs.com** 抓取近一年文章与资源链接，存入本地 SQLite，供后续魔盘站点使用。

> 独立项目，与 `duanjuku-sync` / 剧盘无关。

## 快速开始

```bash
cd ~/mopan-sync
./scripts/crawl_ahhhhfs.sh
./scripts/export_json.sh
```

## 数据位置

| 文件 | 说明 |
|------|------|
| `data/ahhhhfs.db` | SQLite 主库（文章 + 链接 + 分类） |
| `data/ahhhhfs_export.json` | 导出 JSON（可选） |

## 抓取范围

默认：`config.yaml` 中 `after: 2025-06-14` 起的全部文章（约 800 篇/年）。

```bash
# 自定义起始日期
./scripts/crawl_ahhhhfs.sh --after 2025-01-01T00:00:00
```

## 技术说明

- 使用 WordPress REST API（`/wp-json/wp/v2/posts`），绕过 Cloudflare 页面挑战
- 每篇文章保存：标题、摘要、正文 HTML、分类、标签、封面图
- 自动提取链接：夸克 / 百度 / 阿里 / 123pan / 蓝奏 / GitHub 等

## 下一步

1. ~~筛选含网盘链接的文章~~ ✅ `filter_quark.sh`
2. ~~转存流水线~~ ✅ QAS `:5006` + `export_to_qas.sh` + `publish_to_site.sh`
3. ~~本地站点~~ ✅ `~/mopan-site` `:8083`

## 完整工作流

```bash
# 1. 抓取 ahhhhfs（已完成 794 篇）
./scripts/crawl_ahhhhfs.sh

# 2. 筛选夸克链接 → 转存队列（450 条）
./scripts/filter_quark.sh --export data/transfer_queue.json

# 3. 启动魔盘专用 QAS（端口 5006，与剧盘 5005 分开）
docker compose up -d
# 打开 http://localhost:5006 配置夸克 Cookie，执行任务

# 4. 导出待转存任务到 QAS
./scripts/export_to_qas.sh

# 5. 导入目录到魔盘站点（源链接，标记「待转存」）
./scripts/import_catalog.sh

# 6. QAS 转存完成后，创建自有分享并更新站点
./scripts/publish_to_site.sh
```

## 魔盘站点

```bash
cd ~/mopan-site && ./run.sh
# http://localhost:8083
```
