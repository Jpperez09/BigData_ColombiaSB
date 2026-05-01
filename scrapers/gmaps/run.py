"""CLI entry point for the Google Maps scraper.

Usage examples::

    python -m scrapers.gmaps.run --city medellin --category restaurants --limit 20
    python -m scrapers.gmaps.run --city bogota --category beauty_salons \\
        --output data/raw/gmaps/bogota_beauty_salons.parquet
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl
from loguru import logger

from scrapers.gmaps.categories import CATEGORIES
from scrapers.gmaps.cities import CITIES
from scrapers.gmaps.scraper import scrape_gmaps_city_category


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scrapers.gmaps.run",
        description="Scrape Google Maps businesses and save to Parquet.",
    )
    p.add_argument(
        "--city",
        required=True,
        choices=sorted(CITIES),
        help="City slug: medellin or bogota.",
    )
    p.add_argument(
        "--category",
        required=True,
        choices=sorted(CATEGORIES),
        help="Category slug (see scrapers/gmaps/categories.py).",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Max results to return (default: no limit, up to 20 per API page).",
    )
    p.add_argument(
        "--radius",
        type=int,
        default=1000,
        metavar="M",
        help="Search radius in metres around the city centre (default: 1000).",
    )
    p.add_argument(
        "--output",
        default=None,
        help="Output .parquet path. Default: data/raw/gmaps/{city}_{category}_test.parquet",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    """Run the scraper, write Parquet, and print a safe summary.

    Returns:
        0 on success, 1 if the scrape raises an unrecoverable error.
    """
    args = _build_parser().parse_args(argv)

    output = args.output or f"data/raw/gmaps/{args.city}_{args.category}_test.parquet"
    output_path = Path(output)

    try:
        results = scrape_gmaps_city_category(
            city_slug=args.city,
            category_slug=args.category,
            radius_m=args.radius,
            limit=args.limit,
        )
    except Exception as exc:
        logger.error(f"Scrape failed: {exc}")
        return 1

    if not results:
        logger.warning("No results returned — nothing written to disk.")
        return 0

    # Serialise to Parquet via Polars.
    # quality_flags is list[str]; cast explicitly so empty lists don't become List(Null).
    rows = [r.model_dump(mode="json") for r in results]
    df = pl.DataFrame(rows).with_columns(pl.col("quality_flags").cast(pl.List(pl.Utf8)))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(str(output_path))

    print(f"City      : {args.city}")
    print(f"Category  : {args.category}")
    print(f"Rows      : {len(results)}")
    print(f"Output    : {output_path}")
    print(f"Validated : all {len(results)} row(s) passed BusinessRaw")

    return 0


if __name__ == "__main__":
    sys.exit(main())
