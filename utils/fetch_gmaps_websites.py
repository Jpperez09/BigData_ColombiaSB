"""Pull gmaps rows from Supabase and write gmaps_websites.parquet for Instagram seeding.

Three-pass enrichment:
  Pass 1 — instagram_handle column already set by gmaps spider.
  Pass 2 — regex on the website URL itself (e.g. website IS instagram.com/...).
  Pass 3 — visit each remaining website, scrape the HTML for Instagram links.

Checkpoint: data/interim/crawl_checkpoint.json — saves progress so you can
stop with Ctrl+C and resume later without re-crawling sites already visited.

Usage:
    python -m utils.fetch_gmaps_websites              # all three passes
    python -m utils.fetch_gmaps_websites --no-crawl   # pass 1 + 2 only (fast)
    python -m utils.fetch_gmaps_websites --dry-run    # print counts, don't write
"""

from __future__ import annotations

import argparse
import json
import re
import signal
import time
from pathlib import Path

import polars as pl
import requests
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

from utils.supabase_client import get_client  # noqa: E402

_OUT = Path("data/interim/gmaps_websites.parquet")
_CHECKPOINT = Path("data/interim/crawl_checkpoint.json")
_PAGE_SIZE = 1000
_CRAWL_DELAY = 1.5
_CRAWL_TIMEOUT = 8
_MAX_CRAWL = 3000
_SAVE_EVERY = 25  # save checkpoint every N sites crawled

_INSTAGRAM_RE = re.compile(r"instagram\.com/([A-Za-z0-9_.]+)/?", re.IGNORECASE)
_IG_RESERVED = frozenset({"p", "explore", "accounts", "reel", "reels", "stories", "tv"})

_HEADERS = {"User-Agent": "smb-intel-co (research project, contact: juanpaperez2603@gmail.com)"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_handle_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = _INSTAGRAM_RE.search(url)
    if match and match.group(1).lower() not in _IG_RESERVED:
        return match.group(1)
    return None


def _crawl_website(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_CRAWL_TIMEOUT, allow_redirects=True)
        if resp.status_code != 200:
            return None
        for match in _INSTAGRAM_RE.finditer(resp.text):
            handle = match.group(1)
            if handle.lower() not in _IG_RESERVED and len(handle) <= 30:
                return handle
    except Exception:  # noqa: BLE001
        pass
    return None


def _load_checkpoint() -> tuple[dict[str, dict], set[str]]:
    """Load saved enriched handles and set of already-crawled URLs."""
    if not _CHECKPOINT.exists():
        return {}, set()
    data = json.loads(_CHECKPOINT.read_text())
    enriched = {k: v for k, v in data.get("enriched", {}).items()}
    crawled = set(data.get("crawled_urls", []))
    logger.info(f"Checkpoint loaded: {len(enriched)} handles, {len(crawled)} URLs already crawled")
    return enriched, crawled


def _save_checkpoint(enriched: dict[str, dict], crawled: set[str]) -> None:
    _CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    _CHECKPOINT.write_text(
        json.dumps({"enriched": enriched, "crawled_urls": sorted(crawled)}, indent=2)
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def fetch(dry_run: bool = False, no_crawl: bool = False) -> None:
    client = get_client()
    rows: list[dict] = []
    offset = 0

    logger.info("Fetching all gmaps rows from Supabase businesses_raw...")

    while True:
        resp = (
            client.table("businesses_raw")
            .select("name, city, instagram_handle, website, category_raw")
            .eq("source", "gmaps")
            .range(offset, offset + _PAGE_SIZE - 1)
            .execute()
        )
        batch = resp.data or []
        rows.extend(batch)
        logger.info(f"  fetched {len(rows)} rows so far...")
        if len(batch) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE

    logger.info(f"Total gmaps rows: {len(rows)}")

    # Load checkpoint — picks up where a previous run left off
    enriched, crawled_urls = _load_checkpoint()

    # Pass 1 + 2: instagram_handle column and regex on website URL
    needs_crawl: list[dict] = []

    for row in rows:
        handle = row.get("instagram_handle") or _extract_handle_from_url(row.get("website"))
        if handle:
            h = handle.lstrip("@").lower()
            if h not in enriched:
                enriched[h] = {
                    "instagram_handle": handle.lstrip("@"),
                    "city": row["city"],
                    "category_raw": row.get("category_raw"),
                }
        elif row.get("website") and row["website"] not in crawled_urls:
            needs_crawl.append(row)

    logger.info(f"Pass 1+2: {len(enriched)} handles, {len(needs_crawl)} websites left to crawl")

    # Pass 3: crawl remaining websites
    if not no_crawl and needs_crawl:
        to_crawl = needs_crawl[:_MAX_CRAWL]
        logger.info(f"Pass 3: crawling {len(to_crawl)} websites (Ctrl+C to pause)...")
        found = 0

        # Handle Ctrl+C gracefully — save checkpoint before exiting
        stop = False

        def _on_sigint(sig, frame):  # noqa: ANN001
            nonlocal stop
            stop = True

        signal.signal(signal.SIGINT, _on_sigint)

        for i, row in enumerate(to_crawl, 1):
            if stop:
                logger.info("Interrupted — saving checkpoint...")
                break
            time.sleep(_CRAWL_DELAY)
            url = row["website"]
            handle = _crawl_website(url)
            crawled_urls.add(url)
            if handle:
                h = handle.lower()
                if h not in enriched:
                    enriched[h] = {
                        "instagram_handle": handle,
                        "city": row["city"],
                        "category_raw": row.get("category_raw"),
                    }
                    found += 1
            if i % _SAVE_EVERY == 0:
                _save_checkpoint(enriched, crawled_urls)
                logger.info(
                    f"  crawled {i}/{len(to_crawl)}, +{found} new handles (checkpoint saved)"
                )

        _save_checkpoint(enriched, crawled_urls)
        logger.info(f"Pass 3 done: +{found} new handles from website crawl")

        if stop:
            logger.info("Run again to resume from where you stopped.")
            return

    total = len(enriched)
    logger.info(f"Total unique handles: {total} / {len(rows)} gmaps rows")

    if dry_run:
        logger.info("Dry-run — not writing file.")
        return

    if not enriched:
        logger.warning("No usable handles found — check Supabase connection and data.")
        return

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    df = pl.DataFrame(list(enriched.values()))
    df.write_parquet(_OUT)
    logger.info(f"Written {total} rows to {_OUT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-crawl", action="store_true", help="Skip website crawling (pass 3)")
    args = parser.parse_args()
    fetch(dry_run=args.dry_run, no_crawl=args.no_crawl)
