#!/usr/bin/env python3
"""
RPA-style WeChat MP article link collector.

Flow:
1. Open a browser and enter mp.weixin.qq.com.
2. Reuse mp_auth.json if available; otherwise wait for QR login and save it.
3. Open the article editor.
4. Click Hyperlink.
5. Choose another account.
6. Search the account name / wxid and select the target account.
7. Read article rows, extract "View article" links, turn pages until enough.

Usage:
  python wechat_mp_rpa_links.py "目标公众号" 10
  python wechat_mp_rpa_links.py "目标公众号" 10 -o output.json
  python wechat_mp_rpa_links.py "目标公众号" 10 --wechat-id gh_xxxxx --headless
  python wechat_mp_rpa_links.py "目标公众号" 10 --headless --browser-channel chrome
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, time, timedelta
import hashlib
import html
import json
import random
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright


BASE_URL = "https://mp.weixin.qq.com"
AUTH_FILE = Path(__file__).with_name("mp_auth.json")
ACTION_DELAY_MIN = 0.8
ACTION_DELAY_MAX = 2.2
DOWNLOAD_DELAY_MIN = 2.0
DOWNLOAD_DELAY_MAX = 5.0
IMAGE_DELAY_MIN = 0.2
IMAGE_DELAY_MAX = 0.8
RETRIES = 2
MAX_COUNT = 30


def configure_runtime(args: argparse.Namespace) -> None:
    global ACTION_DELAY_MIN, ACTION_DELAY_MAX
    global DOWNLOAD_DELAY_MIN, DOWNLOAD_DELAY_MAX
    global IMAGE_DELAY_MIN, IMAGE_DELAY_MAX
    global RETRIES, MAX_COUNT

    ACTION_DELAY_MIN = max(0, args.delay_min)
    ACTION_DELAY_MAX = max(ACTION_DELAY_MIN, args.delay_max)
    DOWNLOAD_DELAY_MIN = max(0, args.download_delay_min)
    DOWNLOAD_DELAY_MAX = max(DOWNLOAD_DELAY_MIN, args.download_delay_max)
    IMAGE_DELAY_MIN = max(0, args.image_delay_min)
    IMAGE_DELAY_MAX = max(IMAGE_DELAY_MIN, args.image_delay_max)
    RETRIES = max(1, args.retries)
    MAX_COUNT = max(1, args.max_count)

def configure_runtime_from_dict(cfg: dict) -> None:
    global ACTION_DELAY_MIN, ACTION_DELAY_MAX
    global DOWNLOAD_DELAY_MIN, DOWNLOAD_DELAY_MAX
    global IMAGE_DELAY_MIN, IMAGE_DELAY_MAX
    global RETRIES, MAX_COUNT

    ACTION_DELAY_MIN = max(0, cfg.get('action_min', ACTION_DELAY_MIN))
    ACTION_DELAY_MAX = max(ACTION_DELAY_MIN, cfg.get('action_max', ACTION_DELAY_MAX))
    DOWNLOAD_DELAY_MIN = max(0, cfg.get('download_min', DOWNLOAD_DELAY_MIN))
    DOWNLOAD_DELAY_MAX = max(DOWNLOAD_DELAY_MIN, cfg.get('download_max', DOWNLOAD_DELAY_MAX))
    IMAGE_DELAY_MIN = max(0, cfg.get('image_min', IMAGE_DELAY_MIN))
    IMAGE_DELAY_MAX = max(IMAGE_DELAY_MIN, cfg.get('image_max', IMAGE_DELAY_MAX))
    RETRIES = max(1, int(cfg.get('retries', RETRIES)))
    MAX_COUNT = max(1, int(cfg.get('max_count', MAX_COUNT)))



def extract_token(url: str) -> str:
    match = re.search(r"[?&]token=(\d+)", url)
    return match.group(1) if match else ""


def parse_datetime_arg(value: str | None) -> datetime | None:
    if not value:
        return None

    raw = value.strip().lower()
    now = datetime.now()
    base: date | None = None

    if raw.startswith(("today", "今天")):
        base = now.date()
        raw = re.sub(r"^(today|今天)", "", raw).strip()
    elif raw.startswith(("yesterday", "昨天")):
        base = now.date() - timedelta(days=1)
        raw = re.sub(r"^(yesterday|昨天)", "", raw).strip()

    raw = raw.replace("点", ":00").replace("：", ":")
    raw = re.sub(r"\s+", " ", raw).strip()

    if base:
        if not raw:
            return datetime.combine(base, time.min)
        match = re.search(r"(\d{1,2})(?::(\d{1,2}))?", raw)
        if not match:
            raise ValueError(f"Cannot parse time: {value}")
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        return datetime.combine(base, time(hour=hour, minute=minute))

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
    ):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed
        except ValueError:
            pass
    raise ValueError(f"Cannot parse datetime: {value}")


def parse_article_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    raw = raw.replace("年", "-").replace("月", "-").replace("日", " ")
    raw = raw.replace("/", "-")
    raw = re.sub(r"\s+", " ", raw).strip()
    match = re.search(r"(\d{4}-\d{1,2}-\d{1,2})(?:\s+(\d{1,2}:\d{1,2})(?::\d{1,2})?)?", raw)
    if not match:
        return None
    date_part = match.group(1)
    time_part = match.group(2) or "00:00"
    try:
        return datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def datetime_in_range(value: datetime | None, since: datetime | None, until: datetime | None) -> bool:
    if value is None:
        return True
    if since and value < since:
        return False
    if until and value >= until:
        return False
    return True


def article_url_hash(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:12]


async def short_wait(page, ms: int = 800) -> None:
    await page.wait_for_timeout(ms)


async def human_pause(label: str = "", min_s: float | None = None, max_s: float | None = None) -> None:
    low = ACTION_DELAY_MIN if min_s is None else min_s
    high = ACTION_DELAY_MAX if max_s is None else max_s
    seconds = random.uniform(low, max(low, high))
    if label:
        print(f"[pause] {label}: {seconds:.1f}s")
    await asyncio.sleep(seconds)


async def retry_step(label: str, action):
    last_error: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            return await action()
        except Exception as exc:
            last_error = exc
            if attempt >= RETRIES:
                break
            backoff = random.uniform(2.0 * attempt, 4.0 * attempt)
            print(f"[retry] {label} failed ({attempt}/{RETRIES}); wait {backoff:.1f}s: {exc}")
            await asyncio.sleep(backoff)
    raise last_error or RuntimeError(f"{label} failed")


async def step_login(browser, *, headless: bool):
    """Open MP backend and return an authenticated page/context."""
    context_options = {
        "viewport": {"width": 1365, "height": 900},
        "locale": "zh-CN",
    }

    if AUTH_FILE.exists():
        context = await browser.new_context(
            storage_state=str(AUTH_FILE),
            **context_options,
        )
        page = await context.new_page()
        try:
            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
            await human_pause("after login-state check", 1.5, 3.5)
            if extract_token(page.url):
                print("[login] existing mp_auth.json is valid")
                return page, context
        except Exception as exc:
            print(f"[login] saved state failed: {exc}")
        await context.close()

    if headless:
        raise RuntimeError("mp_auth.json is missing or expired. Run once without --headless and scan QR.")

    context = await browser.new_context(**context_options)
    page = await context.new_page()
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    print("[login] scan the QR code in the opened browser window")
    await page.wait_for_function("() => location.href.includes('token=')", timeout=120_000)
    if "lang=en_US" in page.url:
        await page.goto(page.url.replace("lang=en_US", "lang=zh_CN"), wait_until="domcontentloaded")
    await human_pause("after qr login", 1.0, 2.5)
    await context.storage_state(path=str(AUTH_FILE))
    print(f"[login] saved state to {AUTH_FILE}")
    return page, context


async def step_open_editor(context, token: str):
    """Open the article editor. This is the stable target of clicking 'Article'."""
    editor_url = (
        f"{BASE_URL}/cgi-bin/appmsg?"
        f"t=media/appmsg_edit_v2&action=edit&isNew=1&type=77"
        f"&createType=0&token={token}&lang=zh_CN"
    )
    page = await context.new_page()
    await page.goto(editor_url, wait_until="domcontentloaded", timeout=30_000)
    await human_pause("after editor open", 2.0, 4.0)
    print("[editor] opened article editor")
    return page


async def step_open_hyperlink_dialog(page) -> None:
    """Click toolbar item: Hyperlink / 超链接."""
    toolbar_link = page.locator("li.tpl_item").filter(has_text="超链接")
    if await toolbar_link.count() != 1:
        toolbar_link = page.get_by_text("超链接", exact=True).first
    await human_pause("before hyperlink click")
    await toolbar_link.click(timeout=10_000)
    await page.get_by_role("heading", name="编辑超链接").wait_for(state="visible", timeout=15_000)
    await human_pause("after hyperlink dialog", 0.8, 1.8)
    print("[dialog] hyperlink dialog opened")


async def step_choose_other_account(page, account: str, wechat_id: str | None) -> None:
    """Search and select another public account."""
    choose_btn = page.get_by_role("button", name="选择其他账号")
    await human_pause("before choose account")
    await choose_btn.click(timeout=10_000)

    search_input = page.get_by_placeholder("输入文章来源的账号名称或微信号，回车进行搜索", exact=True)
    await search_input.wait_for(state="visible", timeout=15_000)
    await human_pause("before account search")
    await search_input.fill(account)
    await human_pause("before search enter", 0.4, 1.2)
    await search_input.press("Enter")
    await page.locator("li.inner_link_account_item").first.wait_for(state="visible", timeout=15_000)

    account_items = page.locator("li.inner_link_account_item")
    count = await account_items.count()
    target_index = 0

    for index in range(count):
        text = (await account_items.nth(index).inner_text()).strip()
        exact_name = text.splitlines()[0].strip() == account
        exact_wxid = bool(wechat_id and f"微信号：{wechat_id}" in text)
        if exact_wxid or exact_name:
            target_index = index
            break

    selected_text = (await account_items.nth(target_index).inner_text()).strip().replace("\n", " ")
    await human_pause("before account select")
    await account_items.nth(target_index).click(timeout=10_000)
    await page.locator("label.inner_link_article_item").first.wait_for(state="visible", timeout=15_000)
    await human_pause("after account select", 1.0, 2.5)
    print(f"[account] selected {selected_text}")


async def read_visible_articles(page) -> list[dict[str, str]]:
    return await page.evaluate(
        """
        () => Array.from(document.querySelectorAll('label.inner_link_article_item'))
          .map((el) => {
            const title =
              (el.querySelector('.inner_link_article_title')?.innerText ||
               el.querySelector('.inner_link_article_span')?.innerText ||
               '').trim();
            const rawDate = (el.querySelector('.inner_link_article_date')?.innerText || '').trim();
            const date = rawDate.replace(/\\s*查看文章\\s*$/, '');
            const href = el.querySelector('a[href^="https://mp.weixin.qq.com/s/"]')?.href || '';
            return { title, date, href };
          })
          .filter((item) => item.title);
        """
    )


async def ensure_article_links_rendered(page) -> None:
    articles = await read_visible_articles(page)
    if articles and articles[0].get("href"):
        return
    first = page.locator("label.inner_link_article_item").first
    await human_pause("before first article select", 0.6, 1.6)
    await first.click(timeout=10_000)
    await human_pause("after first article select", 0.6, 1.4)


async def step_extract_articles(page, limit: int) -> list[dict[str, str]]:
    """Extract current page, then click next page until limit is reached.

    When --since/--until is set, scans up to --scan-limit pages, filtering
    candidates by list-page date. Out-of-range early articles stop the scan.
    """
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    page_no = 1
    mod = sys.modules[__name__]
    max_pages = getattr(mod, "_scan_limit", 200)
    date_since = getattr(mod, "_date_since", None)
    date_until = getattr(mod, "_date_until", None)
    has_date_filter = date_since is not None or date_until is not None

    while len(results) < limit:
        await ensure_article_links_rendered(page)
        articles = await read_visible_articles(page)

        for article in articles:
            href = article.get("href", "")
            title = article.get("title", "")
            date_str = article.get("date", "")
            if not href or href in seen or len(href) < 20:
                continue
            seen.add(href)

            # Coarse date filter from list page (Y-M-D only, no time)
            if has_date_filter:
                list_dt = parse_article_datetime(date_str)
                if list_dt and not datetime_in_range(list_dt, date_since, date_until):
                    if date_since and list_dt < date_since:
                        print(f"[date] \u505c\u6b62\u626b\u63cf: {date_str} < --since")
                        return results[:limit]
                    continue

            results.append(
                {
                    "title": title,
                    "date": article.get("date", ""),
                    "url": href,
                }
            )
            print(f"[article {len(results):02d}] {title}")
            if len(results) >= limit:
                break

        if len(results) >= limit:
            break

        first_title = articles[0]["title"] if articles else ""
        next_btn = page.get_by_role("link", name="下一页")
        if await next_btn.count() == 0:
            print("[page] no next page")
            break

        await human_pause("before next page", 1.2, 3.0)
        await next_btn.click(timeout=10_000)
        page_no += 1
        await page.wait_for_function(
            """(oldTitle) => {
              const first = document.querySelector('label.inner_link_article_item .inner_link_article_title');
              return first && first.innerText.trim() && first.innerText.trim() !== oldTitle;
            }""",
            arg=first_title,
            timeout=15_000,
        )
        print(f"[page] moved to page {page_no}")

    if has_date_filter:
        print(f"[date] \u626b\u63cf {page_no} \u9875\uff0c\u7b5b\u9009\u5f97\u5230 {len(results)} \u7bc7\u5019\u9009\u6587\u7ae0")

    return results[:limit]


def safe_filename(value: str, fallback: str, max_len: int = 80) -> str:
    value = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", value).strip(" ._")
    value = re.sub(r"\s+", " ", value)
    if not value:
        value = fallback
    return value[:max_len].rstrip(" ._")


def build_download_html(meta: dict[str, str], body_html: str, source_url: str) -> str:
    title = html.escape(meta.get("title") or "微信文章")
    author = html.escape(meta.get("author") or "")
    pub_time = html.escape(meta.get("pub_time") or "")
    source_url_escaped = html.escape(source_url)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title}</title>
<style>
body {{
  max-width: 677px;
  margin: 0 auto;
  padding: 20px 16px;
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
  color: #333;
  line-height: 1.75;
}}
.article-meta {{
  color: #888;
  font-size: 14px;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid #eee;
}}
.article-meta span {{ margin-right: 16px; }}
.source {{ word-break: break-all; }}
img {{ max-width: 100%; height: auto; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div class="article-meta">
  <span>{author}</span>
  <span>{pub_time}</span>
  <div class="source">{source_url_escaped}</div>
</div>
<div id="js_content">
{body_html}
</div>
</body>
</html>"""


def fix_wechat_lazy_images(body_html: str) -> str:
    """Make WeChat lazy-loaded images work in saved standalone HTML.

    WeChat stores the real image in data-src. The src may be a transparent SVG,
    a lazy webp URL, or absent. Local HTML has no WeChat lazy loader, so copy
    data-src back to src. This is especially important for data-type="gif".
    """

    def fix_img(match: re.Match[str]) -> str:
        tag = match.group(0)
        data_src_match = re.search(r'\sdata-src="([^"]+)"', tag)
        if not data_src_match:
            return tag

        real_src = data_src_match.group(1)
        src_match = re.search(r'\ssrc="([^"]*)"', tag)
        should_replace = True
        if src_match:
            current_src = src_match.group(1)
            should_replace = (
                not current_src
                or current_src.startswith("data:image/")
                or "wx_lazy=1" in current_src
                or "js_img_placeholder" in tag
                or "wx_img_placeholder" in tag
                or 'data-type="gif"' in tag
            )

        if src_match and should_replace:
            tag = tag[: src_match.start()] + f' src="{real_src}"' + tag[src_match.end():]
        elif not src_match:
            tag = tag[:4] + f' src="{real_src}"' + tag[4:]

        tag = tag.replace(" js_img_placeholder", "").replace(" wx_img_placeholder", "")
        return tag

    return re.sub(r"<img\b[^>]*>", fix_img, body_html, flags=re.IGNORECASE | re.DOTALL)


def image_extension_from_url(url: str) -> str:
    parsed = urlparse(html.unescape(url))
    query = parse_qs(parsed.query)
    fmt = (query.get("wx_fmt") or query.get("tp") or [""])[0].lower()
    if fmt in {"jpeg", "jpg"}:
        return ".jpg"
    if fmt in {"png", "gif", "webp"}:
        return f".{fmt}"

    suffix = Path(parsed.path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}:
        return ".jpg" if suffix == ".jpeg" else suffix
    return ".jpg"


def collect_image_src_values(body_html: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r'<img\b[^>]*\ssrc="([^"]+)"', body_html, flags=re.IGNORECASE | re.DOTALL):
        value = match.group(1)
        if not value.startswith("http"):
            continue
        key = html.unescape(value).split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        values.append(value)
    return values


async def localize_article_images(context, body_html: str, article_url: str, download_dir: Path) -> tuple[str, int]:
    src_values = collect_image_src_values(body_html)
    if not src_values:
        return body_html, 0

    asset_dir = download_dir / "images"
    asset_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for src_value in src_values:
        await human_pause("before image download", IMAGE_DELAY_MIN, IMAGE_DELAY_MAX)
        request_url = html.unescape(src_value).split("#", 1)[0]
        filename = hashlib.md5(request_url.encode("utf-8")).hexdigest()[:12] + image_extension_from_url(request_url)
        output_path = asset_dir / filename
        relative_path = f"../images/{filename}"

        if not output_path.exists():
            try:
                response = await context.request.get(request_url, headers={"Referer": article_url}, timeout=30_000)
                if not response.ok:
                    print(f"[image] skip {response.status}: {request_url[:100]}")
                    continue
                output_path.write_bytes(await response.body())
            except Exception as exc:
                print(f"[image] failed: {request_url[:100]} ({exc})")
                continue

        for old in {src_value, html.unescape(src_value), html.unescape(src_value).replace("&", "&amp;")}:
            body_html = body_html.replace(old, relative_path)
        count += 1

    return body_html, count



def find_existing_html(download_dir: Path, url_hash: str) -> Path | None:
    """Return the path of an existing HTML file whose name contains url_hash, or None."""
    if not download_dir.is_dir():
        return None
    try:
        for f in download_dir.iterdir():
            if f.suffix.lower() == ".html" and url_hash in f.stem:
                return f
    except OSError:
        pass
    return None

async def download_one_article(context, article: dict[str, str], index: int, download_dir: Path, *, account_name: str = "") -> dict[str, str]:
    url_hash = article_url_hash(article["url"])

    # Skip if already downloaded
    existing = find_existing_html(download_dir, url_hash)
    if existing:
        print(f"[download {index:02d}] SKIP (exists): {existing}")
        return {**article, "file": str(existing), "image_count": "0", "skipped": "true"}

    page = await context.new_page()
    try:
        await page.goto(article["url"], wait_until="load", timeout=45_000)
        await page.wait_for_selector("#js_content", timeout=30_000)
        await short_wait(page, 1000)
        meta = await page.evaluate(
            """
            () => {
              const meta = (selector) => document.querySelector(selector)?.getAttribute('content') || '';
              const text = (selector) => document.querySelector(selector)?.textContent?.trim() || '';
              return {
                title: meta('meta[property="og:title"]') || text('#activity-name') || document.title,
                author: meta('meta[property="og:article:author"]') || text('#js_name'),
                pub_time: text('#publish_time') || text('#js_publish_time'),
                body_html: document.querySelector('#js_content')?.innerHTML || ''
              };
            }
            """
        )
        title = meta.get("title") or article.get("title") or f"article_{index:02d}"
        body_html = fix_wechat_lazy_images(meta.get("body_html", ""))
        pub_dt = parse_article_datetime(meta.get("pub_time", "") or article.get("date", ""))
        date_prefix = pub_dt.strftime("%Y-%m-%d") if pub_dt else datetime.now().strftime("%Y-%m-%d")
        acct_subdir = download_dir / safe_filename(account_name or "unknown", "unknown")
        acct_subdir.mkdir(parents=True, exist_ok=True)
        output_path = acct_subdir / f"{date_prefix}_{safe_filename(title, f'article_{index:02d}')}.html"
        body_html, image_count = await localize_article_images(
            context,
            body_html,
            article["url"],
            download_dir,
        )
        output_path.write_text(
            build_download_html(meta, body_html, article["url"]),
            encoding="utf-8-sig",
        )
        print(f"[download {index:02d}] {output_path} ({image_count} images)")
        return {**article, "file": str(output_path), "image_count": str(image_count)}
    finally:
        await page.close()


async def step_download_articles(context, articles: list[dict[str, str]], download_dir: Path, *, account_name: str = "") -> list[dict[str, str]]:
    download_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[dict[str, str]] = []
    for index, article in enumerate(articles, start=1):
        if index > 1:
            await human_pause("between article downloads", DOWNLOAD_DELAY_MIN, DOWNLOAD_DELAY_MAX)
        try:
            downloaded.append(
                await retry_step(
                    f"download article {index}",
                    lambda article=article, index=index: download_one_article(context, article, index, download_dir, account_name=account_name),
                )
            )
        except Exception as exc:
            print(f"[download {index:02d}] failed: {article.get('title', '')} ({exc})")
            downloaded.append({**article, "file": "", "download_error": str(exc)})
    return downloaded


async def run_rpa(
    account: str,
    limit: int,
    *,
    output: Path | None,
    headless: bool,
    browser_channel: str | None,
    browser_executable: Path | None,
    wechat_id: str | None,
    download: bool,
    download_dir: Path,
) -> dict[str, Any]:
    if limit > MAX_COUNT:
        raise ValueError(f"count {limit} is above --max-count {MAX_COUNT}. Split into smaller batches.")

    async with async_playwright() as playwright:
        launch_options: dict[str, Any] = {
            "headless": headless,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if browser_channel:
            launch_options["channel"] = browser_channel
        if browser_executable:
            launch_options["executable_path"] = str(browser_executable)

        browser = await playwright.chromium.launch(**launch_options)
        home_page, context = await step_login(browser, headless=headless)
        try:
            token = extract_token(home_page.url)
            if not token:
                raise RuntimeError("Could not find token after login.")

            editor_page = await step_open_editor(context, token)
            await step_open_hyperlink_dialog(editor_page)
            await step_choose_other_account(editor_page, account, wechat_id)
            articles = await step_extract_articles(editor_page, limit)
            if download:
                articles = await step_download_articles(context, articles, download_dir, account_name=account)

            payload = {
                "account": account,
                "wechat_id": wechat_id,
                "requested": limit,
                "total": len(articles),
                "download": download,
                "download_dir": str(download_dir) if download else "",
                "articles": articles,
            }

            if output:
                output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8-sig")
                print(f"[output] saved {output}")

            return payload
        finally:
            await context.close()
            await browser.close()


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RPA-style WeChat MP article link collector")
    parser.add_argument("account", help="Public account name.")
    parser.add_argument("count", nargs="?", type=int, default=10, help="Number of links to collect")
    parser.add_argument("-o", "--output", type=Path, help="Save result JSON to this path")
    parser.add_argument("--wechat-id", help="Optional exact wxid.")
    parser.add_argument("--headless", action="store_true", help="Run headless. Requires valid mp_auth.json.")
    parser.add_argument("--browser-channel", help="Use an installed browser channel, e.g. chrome or msedge.")
    parser.add_argument("--browser-executable", type=Path, help="Use a local browser executable path.")
    parser.add_argument("--download", action="store_true", help="Download article HTML after collecting links.")
    parser.add_argument("--download-dir", type=Path, default=Path("downloaded_articles"), help="Directory for article HTML files.")
    parser.add_argument("--delay-min", type=float, default=0.8, help="Minimum random delay between UI actions, seconds.")
    parser.add_argument("--delay-max", type=float, default=2.2, help="Maximum random delay between UI actions, seconds.")
    parser.add_argument("--download-delay-min", type=float, default=2.0, help="Minimum delay between article downloads, seconds.")
    parser.add_argument("--download-delay-max", type=float, default=5.0, help="Maximum delay between article downloads, seconds.")
    parser.add_argument("--image-delay-min", type=float, default=0.2, help="Minimum delay between image downloads, seconds.")
    parser.add_argument("--image-delay-max", type=float, default=0.8, help="Maximum delay between image downloads, seconds.")
    parser.add_argument("--retries", type=int, default=2, help="Retry attempts for article downloads.")
    parser.add_argument("--max-count", type=int, default=30, help="Safety limit for one run.")
    parser.add_argument("--since", help="Only collect articles published on or after this time. E.g. '\u6628\u59299\u70b9', 'today 9:00', '2026-06-10 09:00'.")
    parser.add_argument("--until", help="Only collect articles published before this time. E.g. '\u4eca\u59299\u70b9', 'today 9:00', '2026-06-11 09:00'.")
    parser.add_argument("--scan-limit", type=int, default=200, help="Max pages to scan when using --since/--until. Default 200.")
    args = parser.parse_args(argv)
    if args.browser_channel and args.browser_executable:
        parser.error("--browser-channel and --browser-executable cannot be used together.")
    if args.browser_executable and not args.browser_executable.exists():
        parser.error(f"--browser-executable does not exist: {args.browser_executable}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    configure_runtime(args)

    # Set module-level date filter variables
    mod = sys.modules[__name__]
    mod._date_since = parse_datetime_arg(args.since)
    mod._date_until = parse_datetime_arg(args.until)
    mod._scan_limit = args.scan_limit
    if mod._date_since or mod._date_until:
        print(f"[date] filter: since={mod._date_since} until={mod._date_until} scan-limit={mod._scan_limit}")

    try:
        payload = asyncio.run(
            run_rpa(
                args.account,
                args.count,
                output=args.output,
                headless=args.headless,
                browser_channel=args.browser_channel,
                browser_executable=args.browser_executable,
                wechat_id=args.wechat_id,
                download=args.download,
                download_dir=args.download_dir,
            )
        )
    except PlaywrightTimeoutError as exc:
        print(f"[error] page operation timed out: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["total"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
