"""Join Instagram parquet with gmaps metrics from the crawl checkpoint.

The crawl checkpoint (data/interim/crawl_checkpoint.json) stores gmaps_rating,
gmaps_reviews_count, gmaps_name, and gmaps_website per handle discovered during
the three-pass enrichment. This script joins those fields into the Instagram
parquet to produce a single analysis-ready dataset.

Output: data/interim/ig_gmaps_merged.parquet
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
from loguru import logger

_IG_PATH = Path("data/raw/instagram/profiles.parquet")
_CHECKPOINT = Path("data/interim/crawl_checkpoint.json")
_OUT = Path("data/interim/ig_gmaps_merged.parquet")


def merge() -> None:
    # Load checkpoint — has gmaps_rating/reviews embedded per handle
    data = json.loads(_CHECKPOINT.read_text())
    enriched = data.get("enriched", {})

    gmaps_rows = [
        {
            "handle_key": h,
            "gmaps_rating": v.get("gmaps_rating"),
            "gmaps_reviews_count": v.get("gmaps_reviews_count"),
            "gmaps_name": v.get("gmaps_name"),
            "gmaps_website": v.get("gmaps_website"),
        }
        for h, v in enriched.items()
        if v.get("gmaps_rating") is not None or v.get("gmaps_reviews_count") is not None
    ]

    gmaps_df = pl.DataFrame(gmaps_rows)
    logger.info(f"Handles with gmaps metrics in checkpoint: {len(gmaps_df)}")

    ig = pl.read_parquet(_IG_PATH).with_columns(
        pl.col("instagram_handle").str.to_lowercase().alias("handle_key")
    )

    merged = ig.join(gmaps_df, on="handle_key", how="left").drop("handle_key")

    matched = merged["gmaps_rating"].is_not_null().sum()
    logger.info(f"Merged: {len(merged)} rows, gmaps match rate: {matched}/{len(merged)}")

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    merged.write_parquet(_OUT)
    logger.info(f"Written to {_OUT}")


if __name__ == "__main__":
    merge()
