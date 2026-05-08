"""AI Readiness Score — feature engineering and weighted-sum pipeline (Step 3).

Implements the 7 features specified in the working plan (Section 7.1):

    whatsapp_signal     1.0 if whatsapp_flag, 0.5 if any phone, else 0.0
    instagram_reach     log1p(followers) min-max scaled to [0, 1]
    instagram_activity  decay function on last_post_at: 1.0 if <=7 days,
                        linearly decays to 0.0 at >=180 days
    catalog_signal      1.0 if instagram_has_catalog else 0.0
    review_volume       log1p(reviews_count) min-max scaled to [0, 1]
    vertical_weight     looked up from scoring/vertical_weights.yaml
    geographic_weight   looked up from scoring/geographic_weights.yaml

Each feature returns a value in [0.0, 1.0]. The final score is the weighted
sum (weights from scoring/weights.yaml) normalised to [0, 100] by dividing by
the sum of weights and multiplying by 100.

CLI
---
    python -m scoring.features                 # default settings
    python -m scoring.features --top-n 500
    python -m scoring.features --city Medellín
    python -m scoring.features --min-score 40
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl
import yaml
from loguru import logger

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCORING_DIR = Path(__file__).parent
WEIGHTS_PATH = SCORING_DIR / "weights.yaml"
VERTICAL_WEIGHTS_PATH = SCORING_DIR / "vertical_weights.yaml"
GEO_WEIGHTS_PATH = SCORING_DIR / "geographic_weights.yaml"

CANONICAL_PATH = Path("data/clean/businesses_canonical.parquet")
SCORED_PATH = Path("data/clean/scored.parquet")
TOP_OUT_PATH = Path("data/clean/top_500.csv")

# Optional enrichment: gmaps evidence file with (place_id, zone_name, category_slug).
# When present, we use it to override compound `category_raw` with the canonical
# slug and to fill in missing `neighborhood`.
GMAPS_EVIDENCE_PATH = Path("data/interim/gmaps_place_categories.parquet")

# ---------------------------------------------------------------------------
# Reach / volume scaling — fixed log1p caps so scores are stable across runs
# ---------------------------------------------------------------------------

# log1p of these caps maps to 1.0 in the feature output.
_FOLLOWERS_LOG_CAP = math.log1p(50_000)  # 50k followers → reach = 1.0
_REVIEWS_LOG_CAP = math.log1p(1_000)  # 1000 reviews → review_volume = 1.0

# Activity decay window
_ACTIVITY_FULL_DAYS = 7  # 1.0 if posted within last 7 days
_ACTIVITY_ZERO_DAYS = 180  # 0.0 if last post is >= 180 days old


# ---------------------------------------------------------------------------
# Weight loaders
# ---------------------------------------------------------------------------


def load_weights(path: Path = WEIGHTS_PATH) -> dict[str, float]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["weights"]


def load_vertical_weights(path: Path = VERTICAL_WEIGHTS_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_geographic_weights(path: Path = GEO_WEIGHTS_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Feature functions — each returns a float in [0.0, 1.0]
# ---------------------------------------------------------------------------


def whatsapp_signal(whatsapp_flag: bool | None, phone: str | None) -> float:
    if whatsapp_flag:
        return 1.0
    if phone:
        return 0.5
    return 0.0


def instagram_reach(followers: int | None) -> float:
    if followers is None or followers <= 0:
        return 0.0
    scaled = math.log1p(followers) / _FOLLOWERS_LOG_CAP
    return min(round(scaled, 4), 1.0)


def instagram_activity(
    last_post_at: datetime | None,
    *,
    now: datetime | None = None,
) -> float:
    """1.0 if posted within last 7 days, linear decay to 0.0 at >=180 days."""
    if last_post_at is None:
        return 0.0

    now = now or datetime.now(timezone.utc)
    if last_post_at.tzinfo is None:
        last_post_at = last_post_at.replace(tzinfo=timezone.utc)

    days_old = (now - last_post_at).total_seconds() / 86400
    if days_old < 0:
        return 1.0  # posted "in the future" (clock drift) — treat as fresh
    if days_old <= _ACTIVITY_FULL_DAYS:
        return 1.0
    if days_old >= _ACTIVITY_ZERO_DAYS:
        return 0.0
    span = _ACTIVITY_ZERO_DAYS - _ACTIVITY_FULL_DAYS
    decay = 1.0 - (days_old - _ACTIVITY_FULL_DAYS) / span
    return round(max(0.0, min(decay, 1.0)), 4)


def catalog_signal(has_catalog: bool | None) -> float:
    return 1.0 if has_catalog else 0.0


def review_volume(reviews_count: int | None) -> float:
    if reviews_count is None or reviews_count <= 0:
        return 0.0
    scaled = math.log1p(reviews_count) / _REVIEWS_LOG_CAP
    return min(round(scaled, 4), 1.0)


def vertical_weight(category: str | None, table: dict[str, Any]) -> float:
    if not category:
        return float(table.get("default", 0.7))
    return float(table.get("verticals", {}).get(category, table.get("default", 0.7)))


def geographic_weight(
    city_slug: str | None,
    neighborhood: str | None,
    table: dict[str, Any],
) -> float:
    """Lookup by (city_slug, neighborhood); fall back to city_default then default."""
    cities = table.get("cities", {})
    if city_slug and city_slug in cities:
        zones = cities[city_slug] or {}
        if neighborhood and neighborhood in zones:
            return float(zones[neighborhood])
        return float(table.get("city_default", 0.8))
    return float(table.get("default", 0.6))


# ---------------------------------------------------------------------------
# City-name canonicalisation (data has 'Medellín' / 'Bogotá', YAML uses slugs)
# ---------------------------------------------------------------------------

_CITY_SLUG = {
    "medellín": "medellin",
    "medellin": "medellin",
    "bogotá": "bogota",
    "bogota": "bogota",
}


def _city_to_slug(city: str | None) -> str | None:
    if not city:
        return None
    return _CITY_SLUG.get(city.strip().lower())


# ---------------------------------------------------------------------------
# Per-row scoring
# ---------------------------------------------------------------------------


def score_row(
    row: dict[str, Any],
    *,
    weights: dict[str, float],
    vertical_table: dict[str, Any],
    geographic_table: dict[str, Any],
    now: datetime | None = None,
) -> tuple[float, dict[str, float]]:
    """Compute (score_0_to_100, per_feature_breakdown) for one row."""
    feats: dict[str, float] = {
        "whatsapp_signal": whatsapp_signal(
            row.get("whatsapp_flag"),
            row.get("phone_e164") or row.get("phone_raw"),
        ),
        "instagram_reach": instagram_reach(row.get("instagram_followers")),
        "instagram_activity": instagram_activity(row.get("instagram_last_post_at"), now=now),
        "catalog_signal": catalog_signal(row.get("instagram_has_catalog")),
        "review_volume": review_volume(row.get("reviews_count")),
        "vertical_weight": vertical_weight(row.get("category_raw"), vertical_table),
        "geographic_weight": geographic_weight(
            _city_to_slug(row.get("city")),
            row.get("neighborhood"),
            geographic_table,
        ),
    }

    weight_sum = sum(weights.values())
    weighted = sum(feats[k] * weights[k] for k in weights)
    score = round((weighted / weight_sum) * 100, 2) if weight_sum else 0.0
    return score, feats


def _enrich_from_gmaps_evidence(
    df: pl.DataFrame,
    evidence_path: Path = GMAPS_EVIDENCE_PATH,
) -> pl.DataFrame:
    """If the gmaps evidence file is present, override category_raw + neighborhood.

    The evidence file holds one row per (place_id, zone, category_slug, h3_cell).
    For each gmaps source_id we pick the most-common (zone, category_slug) pair
    and use those as `category_slug_enriched` and `neighborhood_enriched`.

    The originals are preserved; downstream scoring reads enriched first, then
    falls back to the original column.
    """
    if not evidence_path.exists():
        logger.debug(f"No gmaps evidence at {evidence_path} — skipping enrichment.")
        df = df.with_columns(
            pl.col("category_raw").alias("category_slug_enriched"),
            pl.col("neighborhood").alias("neighborhood_enriched"),
        )
        return df

    evidence = pl.read_parquet(str(evidence_path))
    # Pick the most frequent (place_id, zone, category) tuple per place_id
    counts = (
        evidence.group_by(["place_id", "zone_name", "category"])
        .len()
        .sort(["place_id", "len"], descending=[False, True])
    )
    primary = counts.unique(subset=["place_id"], keep="first").select(
        pl.col("place_id"),
        pl.col("zone_name").alias("neighborhood_enriched"),
        pl.col("category").alias("category_slug_enriched"),
    )

    # Join: gmaps canonical rows have source='gmaps' and source_id = place_id
    df = df.join(
        primary,
        left_on="source_id",
        right_on="place_id",
        how="left",
    )
    # For non-gmaps sources keep originals
    df = df.with_columns(
        pl.coalesce(["category_slug_enriched", "category_raw"]).alias("category_slug_enriched"),
        pl.coalesce(["neighborhood_enriched", "neighborhood"]).alias("neighborhood_enriched"),
    )
    n_enriched = df.filter(pl.col("category_slug_enriched") != pl.col("category_raw")).height
    logger.info(
        f"Enriched {n_enriched} rows from {evidence_path.name} "
        f"(category + neighborhood overrides)"
    )
    return df


def compute_scores(df: pl.DataFrame) -> pl.DataFrame:
    """Add `ai_readiness_score` plus per-feature columns to the DataFrame."""
    weights = load_weights()
    vertical_table = load_vertical_weights()
    geographic_table = load_geographic_weights()
    now = datetime.now(timezone.utc)

    df = _enrich_from_gmaps_evidence(df)

    rows = df.to_dicts()
    scores: list[float] = []
    feature_cols: dict[str, list[float]] = {f"feat_{k}": [] for k in weights}

    for row in rows:
        # Prefer enriched fields when present
        scoring_row = dict(row)
        scoring_row["category_raw"] = row.get("category_slug_enriched") or row.get("category_raw")
        scoring_row["neighborhood"] = row.get("neighborhood_enriched") or row.get("neighborhood")
        score, feats = score_row(
            scoring_row,
            weights=weights,
            vertical_table=vertical_table,
            geographic_table=geographic_table,
            now=now,
        )
        scores.append(score)
        for k, v in feats.items():
            feature_cols[f"feat_{k}"].append(v)

    out = df.with_columns(pl.Series("ai_readiness_score", scores))
    for col, values in feature_cols.items():
        out = out.with_columns(pl.Series(col, values))
    return out


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def run(
    top_n: int = 500,
    city_filter: str | None = None,
    min_score: float = 0.0,
    output_path: Path = TOP_OUT_PATH,
    scored_path: Path = SCORED_PATH,
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

    # Always write the full scored parquet (even before filtering)
    scored_path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(str(scored_path))
    logger.info(f"Wrote {len(df)} scored rows → {scored_path}")

    df = df.filter(pl.col("ai_readiness_score") >= min_score)
    df = df.sort("ai_readiness_score", descending=True)

    top = df.head(top_n)
    logger.info(
        f"Top {len(top)} | score range: "
        f"{top['ai_readiness_score'].min():.1f}–{top['ai_readiness_score'].max():.1f}"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    csv_df = top
    for col in csv_df.columns:
        if csv_df[col].dtype == pl.List(pl.Utf8):
            csv_df = csv_df.with_columns(pl.col(col).list.join("|").alias(col))
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
        "--city", default=None, metavar="CITY", help="Filter to a single city (e.g. 'Medellín')."
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
