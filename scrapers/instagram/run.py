"""CLI entry point for the Instagram scraper.

Usage examples:

  # Run from the gmaps seed file (normal flow after Juanpa's spider runs):
  python -m scrapers.instagram.run

  # Run from a manual CSV seed (for testing before gmaps data is ready):
  python -m scrapers.instagram.run --seed path/to/seeds.csv

  # Dry-run: print how many handles would be scraped, then exit:
  python -m scrapers.instagram.run --dry-run
"""

from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger

from scrapers.instagram.scraper import (
    _SEED_PATH,
    load_seed_from_csv,
    load_seed_from_parquet,
    run,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Instagram public-profile scraper")
    parser.add_argument(
        "--seed",
        type=Path,
        default=None,
        help=(
            "Path to a seed file. Parquet uses gmaps_websites schema; "
            "CSV must have columns: handle, city[, category_raw]. "
            "Defaults to data/interim/gmaps_websites.parquet."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/raw/instagram/profiles.parquet"),
        help="Output Parquet path (default: data/raw/instagram/profiles.parquet).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load seeds and print the count, but do not scrape.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    seed_path: Path = args.seed or _SEED_PATH

    if seed_path.suffix == ".csv":
        seeds = load_seed_from_csv(seed_path)
    elif seed_path.suffix == ".parquet":
        seeds = load_seed_from_parquet(seed_path)
    else:
        raise ValueError(f"Unsupported seed file format: {seed_path.suffix}")

    logger.info(f"Seed: {len(seeds)} handles from {seed_path}")

    if args.dry_run:
        logger.info("Dry-run mode — exiting without scraping.")
        return

    results = run(seeds, output_path=args.output)
    logger.info(f"Done. {len(results)} profiles written to {args.output}")


if __name__ == "__main__":
    main()
