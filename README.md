# Linux.do 热门话题中转

GitHub Actions 定时抓取 linux.do 热门话题，输出 `hot.json`，供国内机器拉取。

## 文件说明

- `fetch_linuxdo_hot.py` — 抓取脚本（优先 RSS，兜底 HTML，输出 hot.json）
- `.github/workflows/linuxdo-hot.yml` — Actions 工作流（北京时间 05:30 / 17:30 各跑一次）

## 使用方法

1. 新建一个 GitHub 仓库（Public 或 Private 都行，Public 拉取更简单）
2. 把 `fetch_linuxdo_hot.py` 放到仓库根目录
3. 把 `linuxdo-hot.yml` 放到 `.github/workflows/` 目录
4. 首次手动触发一次：仓库 → Actions → Fetch Linux.do Hot → Run workflow
5. 之后每天自动更新 `hot.json`

## 拉取地址

```
https://raw.githubusercontent.com/<你的用户名>/<仓库名>/main/hot.json
```

## 输出格式

```json
{
  "ok": true,
  "fetched_at": "2026-08-07 17:30:00",
  "count": 30,
  "items": [
    {"title": "...", "link": "https://linux.do/t/...", "author": "...", "source": "rss"}
  ]
}
```
