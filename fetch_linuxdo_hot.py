#!/usr/bin/env python3
"""抓取 linux.do 热门话题，输出 hot.json 供下游使用。

设计：GitHub Actions 定时在境外 runner 跑本脚本 → 把 hot.json commit 回仓库
→ 国内机器从 raw.githubusercontent.com 拉取。

不依赖 Telegram / ScrapingAnt / 任何第三方 key，纯标准库 + requests + bs4。
"""
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

# 允许缺失 requests/bs4 时给出明确错误
try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("依赖缺失：需要 requests 和 beautifulsoup4")
    sys.exit(2)

TARGET_URL = "https://linux.do/hot"
TOP_RSS_URL = "https://linux.do/top.rss?period=daily"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
OUTPUT_FILE = os.environ.get("OUTPUT_FILE", "hot.json")


def fetch(url: str, timeout: int = 30) -> str:
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def parse_rss(xml_text: str) -> list[dict]:
    """从 Discourse 标准 RSS 解析热门话题（比 HTML 稳定）。"""
    from xml.etree import ElementTree as ET
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    for item in root.iter("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        creator_el = item.find("{http://purl.org/dc/elements/1.1/}creator")
        title = (title_el.text or "").strip() if title_el is not None else ""
        link = (link_el.text or "").strip() if link_el is not None else ""
        if title and link:
            items.append({
                "title": title,
                "link": link,
                "author": (creator_el.text or "").strip() if creator_el is not None else "",
                "source": "rss",
            })
    return items


def parse_html(html_text: str) -> list[dict]:
    """解析 linux.do/hot HTML 页面（RSS 失败时兜底）。"""
    soup = BeautifulSoup(html_text, "html.parser")
    items = []
    for a_tag in soup.select("a.raw-link"):
        title = a_tag.get_text(strip=True)
        link = a_tag.get("href", "")
        if len(title) > 3 and "/t/" in link:
            if not link.startswith("http"):
                link = "https://linux.do" + link
            items.append({"title": title, "link": link, "author": "", "source": "html"})
    return items


def main():
    bj_tz = timezone(timedelta(hours=8))
    now_bj = datetime.now(bj_tz).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now_bj}] 开始抓取 {TARGET_URL}")

    items = []
    errors = []

    # 优先 RSS（Discourse 标准，通常不被 CF 拦截）
    for name, url in (("RSS", TOP_RSS_URL), ("HTML", TARGET_URL)):
        try:
            text = fetch(url)
            parsed = parse_rss(text) if name == "RSS" else parse_html(text)
            print(f"  {name}: 拿到 {len(parsed)} 条")
            if parsed:
                items = parsed
                break
        except Exception as e:
            errors.append(f"{name}: {e}")
            print(f"  {name} 失败: {e}")

    if not items:
        payload = {
            "ok": False,
            "error": "; ".join(errors) or "无内容",
            "fetched_at": now_bj,
            "items": [],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        sys.exit(0)  # 失败也提交文件，让下游知道状态；不报错触发告警

    # 去重（按链接）
    seen = set()
    unique = []
    for it in items:
        if it["link"] not in seen:
            seen.add(it["link"])
            unique.append(it)

    payload = {
        "ok": True,
        "fetched_at": now_bj,
        "count": len(unique),
        "items": unique[:30],  # 最多 30 条
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"✓ 已写入 {OUTPUT_FILE}: {len(unique)} 条")
    for it in unique[:10]:
        print(f"  - {it['title'][:50]}")


if __name__ == "__main__":
    main()
