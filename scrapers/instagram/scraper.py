"""Instagram public-profile scraper (no-login mode).

Reads a seed list of (handle, city) pairs — either from Juanpa's
data/interim/gmaps_websites.parquet or from a manual CSV — then fetches
each profile via instaloader and writes validated BusinessRaw rows to
data/raw/instagram/profiles.parquet.

Throttle:   1 request per 2 seconds.
Rate-limit: sleep 15 minutes and resume automatically.
Checkpoint: data/interim/ig_checkpoint.json — set of completed handles.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path

import instaloader
import polars as pl
from loguru import logger
from pydantic import ValidationError

from scrapers.instagram.normalize import profile_to_business_raw
from utils.models import BusinessRaw

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SEED_PATH = Path("data/interim/gmaps_websites.parquet")
_CHECKPOINT_PATH = Path("data/interim/ig_checkpoint.json")
_OUTPUT_PATH = Path("data/raw/instagram/profiles.parquet")

# ---------------------------------------------------------------------------
# Timing
# ---------------------------------------------------------------------------

_REQUEST_DELAY = 2.0  # seconds between requests
_RATE_LIMIT_SLEEP = 900  # 15 minutes when rate-limited


# ---------------------------------------------------------------------------
# Seed loading
# ---------------------------------------------------------------------------


def load_seed_from_parquet(path: Path = _SEED_PATH) -> list[dict]:
    """Load (handle, city, category_raw) triples from gmaps_websites.parquet.

    Returns a list of dicts with keys: handle, city, category_raw (optional).
    Rows with a null or empty instagram_handle are dropped.
    """
    df = pl.read_parquet(path)
    required = {"instagram_handle", "city"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"gmaps_websites.parquet is missing columns: {missing}")

    df = df.filter(pl.col("instagram_handle").is_not_null())
    df = df.filter(pl.col("instagram_handle") != "")

    records = []
    for row in df.iter_rows(named=True):
        records.append(
            {
                "handle": row["instagram_handle"].lstrip("@"),
                "city": row["city"],
                "category_raw": row.get("category_raw"),
            }
        )
    logger.info(f"Loaded {len(records)} handles from {path}")
    return records


def load_seed_from_csv(path: Path) -> list[dict]:
    """Load seeds from a CSV with columns: handle, city[, category_raw].

    Useful for manual testing before gmaps_websites.parquet is available.
    """
    df = pl.read_csv(path)
    records = []
    for row in df.iter_rows(named=True):
        handle = str(row.get("handle", "") or "").strip().lstrip("@")
        city = str(row.get("city", "") or "").strip()
        if not handle or not city:
            continue
        records.append(
            {
                "handle": handle,
                "city": city,
                "category_raw": row.get("category_raw"),
            }
        )
    logger.info(f"Loaded {len(records)} handles from {path}")
    return records


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------


def _load_checkpoint() -> set[str]:
    if _CHECKPOINT_PATH.exists():
        data = json.loads(_CHECKPOINT_PATH.read_text())
        return set(data.get("done", []))
    return set()


def _save_checkpoint(done: set[str]) -> None:
    _CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CHECKPOINT_PATH.write_text(json.dumps({"done": sorted(done)}, indent=2))


# ---------------------------------------------------------------------------
# Core scraper
# ---------------------------------------------------------------------------


def _fetch_profiles(
    seeds: list[dict],
    done: set[str],
) -> Iterator[BusinessRaw]:
    """Yield validated BusinessRaw rows one at a time, updating done in-place."""
    loader = instaloader.Instaloader(
        download_pictures=False,
        download_videos=False,
        download_video_thumbnails=False,
        download_geotags=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
    )

    for seed in seeds:
        handle: str = seed["handle"]
        city: str = seed["city"]

        if handle in done:
            logger.debug(f"Skip (already done): @{handle}")
            continue

        while True:
            try:
                time.sleep(_REQUEST_DELAY)
                profile = instaloader.Profile.from_username(loader.context, handle)
                extra = {}
                if seed.get("category_raw"):
                    extra["category_raw"] = seed["category_raw"]
                business = profile_to_business_raw(profile, city, extra)
                done.add(handle)
                yield business
                break

            except instaloader.exceptions.ProfileNotExistsException:
                logger.warning(f"Profile not found: @{handle} — skipping")
                done.add(handle)
                break

            except instaloader.exceptions.QueryReturnedNotFoundException:
                logger.warning(f"Profile private or removed: @{handle} — skipping")
                done.add(handle)
                break

            except instaloader.exceptions.TooManyRequestsException:
                logger.warning(
                    f"Rate-limited on @{handle}. " f"Sleeping {_RATE_LIMIT_SLEEP // 60} minutes..."
                )
                _save_checkpoint(done)
                time.sleep(_RATE_LIMIT_SLEEP)

            except ValidationError as exc:
                logger.warning(f"Validation failed for @{handle}: {exc}")
                done.add(handle)
                break

            except Exception as exc:  # noqa: BLE001
                logger.error(f"Unexpected error for @{handle}: {exc}")
                done.add(handle)
                break


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(
    seeds: list[dict],
    output_path: Path = _OUTPUT_PATH,
    checkpoint_every: int = 50,
) -> list[BusinessRaw]:
    """Run the Instagram scraper over the given seed list.

    Args:
        seeds:            List of dicts with keys: handle, city, category_raw.
        output_path:      Where to write the output Parquet file.
        checkpoint_every: Save the checkpoint file every N successful fetches.

    Returns:
        List of all validated BusinessRaw instances collected this run.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    done = _load_checkpoint()
    logger.info(f"Checkpoint: {len(done)} handles already done")

    results: list[BusinessRaw] = []

    for business in _fetch_profiles(seeds, done):
        results.append(business)
        logger.info(
            f"[{len(results)}] @{business.instagram_handle} "
            f"({business.city}) — {business.instagram_followers} followers"
        )
        if len(results) % checkpoint_every == 0:
            _save_checkpoint(done)
            logger.info(f"Checkpoint saved ({len(done)} done total)")

    _save_checkpoint(done)

    if results:
        rows = [r.model_dump() for r in results]
        df = pl.DataFrame(rows)
        df.write_parquet(output_path)
        logger.info(f"Wrote {len(results)} rows to {output_path}")
    else:
        logger.warning("No results collected — output file not written")

    return results
