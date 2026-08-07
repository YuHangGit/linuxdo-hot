#!/usr/bin/env python3
"""抓取 linux.do 热门话题，输出 hot.json 供下游使用。

设计：GitHub Actions 定时在境外 runner 跑本脚本 → 把 hot.json commit 回仓库
→ 国内机器从 raw.githubusercontent.com 拉取。

抓取策略（linux.do 有 Cloudflare 盾，403 常见）：
1. 先试 requests + 浏览器头（轻量）
2. 失败则用 Playwright 无头浏览器过盾（需要 playwright 依赖）
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta

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

BROWSER_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}


def fetch_requests(url: str, timeout: int = 30) -> str:
    """轻量方案：requests + 浏览器头。"""
    session = requests.Session()
    try:
        session.get("https://linux.do/", headers=BROWSER_HEADERS, timeout=timeout)
    except Exception:
        pass
    resp = session.get(url, headers=BROWSER_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def fetch_playwright(url: str, timeout: int = 60) -> str:
    """重型方案：Playwright 无头浏览器过 Cloudflare 盾。
    注意：playwright 的 timeout 参数单位是毫秒！
    """
    from playwright.sync_api import sync_playwright
    timeout_ms = timeout * 1000  # 秒 → 毫秒
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(
            user_agent=UA,
            locale="zh-CN",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        page.goto("https://linux.do/", wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(5000)  # 等 CF 盾 JS 执行
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(5000)
        html = page.content()
        browser.close()
        return html


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

    # 第一轮：requests 轻量抓取（RSS 优先，Discourse 标准，通常不被 CF 拦截）
    for name, url in (("RSS", TOP_RSS_URL), ("HTML", TARGET_URL)):
        try:
            text = fetch_requests(url)
            parsed = parse_rss(text) if name == "RSS" else parse_html(text)
            print(f"  requests/{name}: 拿到 {len(parsed)} 条")
            if parsed:
                items = parsed
                break
        except Exception as e:
            errors.append(f"{name}: {e}")
            print(f"  requests/{name} 失败: {e}")

    # 第二轮：Playwright 无头浏览器过 CF 盾（带 3 次背退重试，应对 TMR）
    if not items:
        for attempt in range(3):
            for name, url in (("HTML", TARGET_URL), ("RSS", TOP_RSS_URL)):
                try:
                    text = fetch_playwright(url)
                    parsed = parse_html(text) if name == "HTML" else parse_rss(text)
                    print(f"  playwright[{attempt}]/{name}: 拿到 {len(parsed)} 条")
                    preview = re.sub(r"\s+", " ", text[:150])
                    print(f"  预览: {preview[:120]}")
                    if parsed:
                        items = parsed
                        break
                except Exception as e:
                    errors.append(f"playwright/{name}: {e}")
                    print(f"  playwright[{attempt}]/{name} 失败: {e}")
            if items:
                break
            print(f"  第 {attempt+1} 轮失败，等待背退重试...")
            time.sleep(20 * (attempt + 1))

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
