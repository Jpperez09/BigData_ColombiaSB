"""AI Readiness feature extraction and scoring — Step 3.

Reads ``data/clean/businesses_canonical.parquet``, computes a 0–100 score
per business, and writes ``data/clean/top_500.csv``.

Score components (weights in weights.yaml):
  - has_website          : +15
  - has_phone            : +10
  - has_instagram        : +20
  - instagram_followers  : up to +15 (log-scaled)
  - instagram_active     : +10 (posted in last 90 days)
  - has_catalog          : +10
  - rating_score         : up to +10 (scaled from 0-5 stars)
  - reviews_score        : up to +10 (log-scaled review count)

CLI
---
    python -m scoring.features                      # default settings
    python -m scoring.features --top-n 500          # export top 500
    python -m scoring.features --city Medellín      # single city
    python -m scoring.features --min-score 40       # filter threshold
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import polars as pl
from loguru import logger

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

CANONICAL_PATH = Path("data/clean/businesses_canonical.parquet")
TOP_OUT_PATH = Path("data/clean/top_500.csv")

# ---------------------------------------------------------------------------
# Default weights
# ---------------------------------------------------------------------------

WEIGHTS: dict[str, float] = {
    "has_website": 15.0,
    "has_phone": 10.0,
    "has_instagram": 20.0,
    "instagram_followers_score": 15.0,  # log-scaled 0-15
    "instagram_active": 10.0,
    "has_catalog": 10.0,
    "rating_score": 10.0,  # scaled 0-10
    "reviews_score": 10.0,  # log-scaled 0-10
}

_MAX_SCORE = sum(WEIGHTS.values())  # 100.0


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def _log_scale(value: float | None, zero_at: float, full_at: float, max_pts: float) -> float:
    """Map value onto [0, max_pts] using log scale between zero_at and full_at."""
    if value is None or value <= zero_at:
        return 0.0
    if value >= full_at:
        return max_pts
    ratio = math.log(value - zero_at + 1) / math.log(full_at - zero_at + 1)
    return round(ratio * max_pts, 2)


def compute_scores(df: pl.DataFrame) -> pl.DataFrame:
    """Add an ``ai_readiness_score`` column (0–100) to the DataFrame."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    ninety_days_ago = now.timestamp() - 90 * 86400

    rows = df.to_dicts()
    scores: list[float] = []

    for row in rows:
        s = 0.0

        # Binary signals
        if row.get("website"):
            s += WEIGHTS["has_website"]
        if row.get("phone_e164") or row.get("phone_raw"):
            s += WEIGHTS["has_phone"]
        if row.get("instagram_handle"):
            s += WEIGHTS["has_instagram"]

        # Instagram followers (log-scaled: 0 @ 0 followers, full @ 10k)
        followers = row.get("instagram_followers")
        s += _log_scale(followers, zero_at=0, full_at=10_000, max_pts=WEIGHTS["instagram_followers_score"])

        # Instagram active (posted in last 90 days)
        last_post = row.get("instagram_last_post_at")
        if last_post is not None:
            try:
                ts = last_post.timestamp() if hasattr(last_post, "timestamp") else float(last_post)
                if ts >= ninety_days_ago:
                    s += WEIGHTS["instagram_active"]
            except (TypeError, ValueError):
                pass

        # Instagram catalog
        if row.get("instagram_has_catalog"):
            s += WEIGHTS["has_catalog"]

        # Rating (linear: 0 @ 0 stars, full @ 5 stars)
        rating = row.get("rating")
        if rating is not None:
            s += round((rating / 5.0) * WEIGHTS["rating_score"], 2)

        # Reviews (log-scaled: 0 @ 0 reviews, full @ 500)
        reviews = row.get("reviews_count")
        s += _log_scale(reviews, zero_at=0, full_at=500, max_pts=WEIGHTS["reviews_score"])

        scores.append(round(min(s, _MAX_SCORE), 2))

    return df.with_columns(pl.Series("ai_readiness_score", scores))


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(
    top_n: int = 500,
    city_filter: str | None = None,
    min_score: float = 0.0,
    output_path: Path = TOP_OUT_PATH,
) -> pl.DataFrame:
    if not CANONICAL_PATH.exists():
        logger.error(f"Canonical parquet not found: {CANONICAL_PATH}")
        logger.error("Run entity resolution first: python -m scoring.entity_resolution")
        return pl.DataFrame()

    df = pl.read_parquet(str(CANONICAL_PATH))
    logger.info(f"Loaded {len(df)} canonical businesses")

    if city_filter:
        df = df.filter(pl.col("city") == city_filter)
        logger.info(f"Filtered to city={city_filter!r}: {len(df)} rows")

    df = compute_scores(df)

    df = df.filter(pl.col("ai_readiness_score") >= min_score)
    df = df.sort("ai_readiness_score", descending=True)

    top = df.head(top_n)
    logger.info(
        f"Top {len(top)} businesses | "
        f"score range: {top['ai_readiness_score'].min():.1f}–{top['ai_readiness_score'].max():.1f}"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Flatten any list/struct columns that CSV can't serialize
    csv_df = top
    for col in csv_df.columns:
        if csv_df[col].dtype == pl.List(pl.Utf8):
            csv_df = csv_df.with_columns(
                pl.col(col).list.join("|").alias(col)
            )
    csv_df.write_csv(str(output_path))
    logger.info(f"Wrote {len(top)} rows → {output_path}")
    return top


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scoring.features",
        description="Compute AI Readiness scores and export top-N businesses.",
    )
    p.add_argument(
        "--top-n",
        type=int,
        default=500,
        metavar="N",
        help="Export top N businesses by score (default 500).",
    )
    p.add_argument(
        "--city",
        default=None,
        metavar="CITY",
        help="Filter to a single city (e.g. 'Medellín').",
    )
    p.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        metavar="S",
        help="Exclude businesses below this score (0–100).",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=TOP_OUT_PATH,
        metavar="PATH",
        help=f"Output CSV path (default {TOP_OUT_PATH}).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    run(
        top_n=args.top_n,
        city_filter=args.city,
        min_score=args.min_score,
        output_path=args.output,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
