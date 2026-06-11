#!/usr/bin/env python3
"""
Daily batch crawler: read crawl_tasks.json, determine the active time slot,
then crawl each public account with --since/--until auto-generated.

Designed for Windows Task Scheduler triggers at 0:00 and 12:00 each day.

Time slot logic (at trigger time 12:00 or 0:00):
  - 12:00 trigger → since=today 0:00, until=today 12:00
  - 0:00  trigger → since=yesterday 12:00, until=today 0:00

Each run:
  1. Read crawl_tasks.json
  2. Compute since/until from clock
  3. For each account, call wechat_mp_rpa_links.run_rpa(...)
  4. Existing articles are auto-skipped (URL-hash dedup)
  5. Write per-account result JSON to daily_crawl_results/
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

import wechat_mp_rpa_links as rpa

RESULT_DIR = Path("daily_crawl_results")


def load_config(config_path: str = "crawl_tasks.json") -> dict[str, Any]:
    raw = Path(config_path).read_text(encoding="utf-8")
    cfg = json.loads(raw)
    if "accounts" not in cfg or not isinstance(cfg["accounts"], list):
        raise ValueError("crawl_tasks.json: missing 'accounts' list")
    return cfg


def compute_time_slot() -> tuple[datetime, datetime, str]:
    """Determine since/until based on current clock time.

    Returns (since, until, slot_name).
    """
    now = datetime.now()
    hour = now.hour

    if 0 <= hour < 12:
        since = (now - timedelta(hours=12)).replace(minute=0, second=0, microsecond=0)
        until = now.replace(minute=0, second=0, microsecond=0)
        slot = "0-12h (yesterday 12:00 until today 0:00)"
    else:
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        until = now.replace(hour=12, minute=0, second=0, microsecond=0)
        slot = "12-24h (today 0:00 until today 12:00)"

    return since, until, slot


async def crawl_account(
    account_cfg: dict[str, Any],
    since: datetime,
    until: datetime,
    download: bool,
    download_dir: Path,
    max_count: int,
    scan_limit: int,
    headless: bool,
    browser_channel: str | None,
    browser_executable: Path | None,
) -> dict[str, Any]:
    name = account_cfg["name"]
    wechat_id = account_cfg.get("wechat_id")
    max_articles = account_cfg.get("max_articles", 10)

    print(f"\n{'=' * 60}")
    print(f"[crawl] {name} (wxid={wechat_id})  max={max_articles}")
    print(f"[crawl] slot: {since.strftime('%Y-%m-%d %H:%M')} -> {until.strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 60}")

    mod = sys.modules["wechat_mp_rpa_links"]
    mod._date_since = since
    mod._date_until = until
    mod._scan_limit = scan_limit

    async with asyncio.timeout(600):
        return await rpa.run_rpa(
            account=name,
            limit=max_articles,
            output=RESULT_DIR / f"{name}_{since.strftime('%Y%m%d_%H%M')}.json",
            headless=headless,
            browser_channel=browser_channel,
            browser_executable=browser_executable,
            wechat_id=wechat_id,
            download=download,
            download_dir=download_dir,
        )


async def main_async() -> None:
    cfg = load_config()
    download = cfg.get("download_articles", True)
    download_dir = Path(cfg.get("download_dir", "daily_articles"))
    max_count = cfg.get("max_count", 30)
    scan_limit = cfg.get("scan_limit", 50)
    headless = bool(cfg.get("headless", False))
    browser_channel = cfg.get("browser_channel") or None
    browser_executable_raw = cfg.get("browser_executable") or None
    browser_executable = Path(browser_executable_raw) if browser_executable_raw else None

    rpa.configure_runtime_from_dict({
        "action_min": cfg.get("delay_min", 1.0),
        "action_max": cfg.get("delay_max", 2.5),
        "download_min": cfg.get("download_delay_min", 2.0),
        "download_max": cfg.get("download_delay_max", 5.0),
        "image_min": cfg.get("image_delay_min", 0.2),
        "image_max": cfg.get("image_delay_max", 0.8),
        "retries": cfg.get("retries", 2),
        "max_count": max_count,
    })

    since, until, slot = compute_time_slot()
    now = datetime.now()
    print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Daily crawl starting")
    print(f"[slot] {slot}")
    print(f"[accounts] {len(cfg['accounts'])}")

    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    successes: list[str] = []
    failures: list[str] = []

    for account_cfg in cfg["accounts"]:
        try:
            result = await crawl_account(
                account_cfg,
                since=since,
                until=until,
                download=download,
                download_dir=download_dir,
                max_count=max_count,
                scan_limit=scan_limit,
                headless=headless,
                browser_channel=browser_channel,
                browser_executable=browser_executable,
            )
            total = result.get("total", 0)
            successes.append(f"{account_cfg['name']}: {total} articles")
        except Exception as exc:
            msg = f"{account_cfg['name']}: {exc}"
            print(f"[FAIL] {msg}", file=sys.stderr)
            failures.append(msg)

    now = datetime.now()
    print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] Daily crawl finished")
    print(f"[ok] {len(successes)}: {'; '.join(successes)}")
    if failures:
        print(f"[fail] {len(failures)}: {'; '.join(failures)}")


def main() -> int:
    try:
        asyncio.run(main_async())
    except PlaywrightTimeoutError as exc:
        print(f"[error] timeout: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
