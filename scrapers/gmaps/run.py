"""CLI entry point for the Google Maps scraper (target-zone H3 strategy).

Re-exports ``regenerate_websites_handoff`` so scripts can rebuild the
Instagram-scraper handoff parquet without re-running the API scrape.

Common invocations
------------------

Dry-run the grid (no API calls)::

    python -m scrapers.gmaps.run --dry-run-grid --all-cities --priority-max 2

Pre-flight cost estimate (no API calls)::

    python -m scrapers.gmaps.run --estimate-cost --all-cities --all-categories \\
        --priority-max 2 --budget-cap-usd 275

Cheap smoke run (single zone, single category, capped hexes)::

    python -m scrapers.gmaps.run --city medellin --zone el_poblado_provenza_lleras \\
        --category restaurants --limit-hexes 5 --budget-cap-usd 25

Full production scrape::

    python -m scrapers.gmaps.run --all-cities --all-categories \\
        --priority-max 2 --resolution 7 --max-resolution 9 --budget-cap-usd 275
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import asdict
from pathlib import Path

import polars as pl
from loguru import logger

from scrapers.gmaps.categories import CATEGORIES, get_categories_by_priority
from scrapers.gmaps.cities import CITIES, get_city
from scrapers.gmaps.cost import (
    BudgetEstimateExceededError,
    BudgetExceededError,
    CostTracker,
    assert_within_budget,
)
from scrapers.gmaps.h3_grid import H3Cell, generate_target_grid
from scrapers.gmaps.scraper import scrape_cells_for_category
from scrapers.gmaps.target_zones import list_all_zone_names

ALL_CITIES = sorted(CITIES)


# ---------------------------------------------------------------------------
# Instagram-handle extraction (handoff to Leo's instagram scraper)
# ---------------------------------------------------------------------------

# Instagram usernames: lowercase letters, digits, period, underscore. Length 1-30.
_IG_USERNAME_RE = re.compile(r"^[a-z0-9._]{1,30}$")

# First-path-segment keywords on instagram.com that are NOT usernames.
_IG_RESERVED = frozenset(
    {
        "p",
        "reel",
        "reels",
        "tv",
        "stories",
        "explore",
        "accounts",
        "about",
        "web",
        "direct",
        "hashtag",
        "developer",
        "developers",
        "ads",
        "legal",
        "press",
        "blog",
        "help",
        "support",
        "ig",
        "contact",
    }
)

# Match the first path segment after instagram.com / instagr.am
_IG_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:instagram\.com|instagr\.am)/(?:#!/)?([^/?\s#]+)",
    re.IGNORECASE,
)


def extract_instagram_handle(url: str | None) -> str | None:
    """Pull an Instagram username out of a URL, or return None.

    Recognises instagram.com and instagr.am hosts. Returns the bare
    username (no leading ``@``), lowercased. Reserved paths like
    ``/p/...`` (post), ``/reel/...``, ``/explore`` are rejected.
    """
    if not url:
        return None
    m = _IG_URL_RE.search(url)
    if not m:
        return None
    candidate = m.group(1).strip().lower().rstrip("/")
    if not candidate or candidate in _IG_RESERVED:
        return None
    if not _IG_USERNAME_RE.match(candidate):
        return None
    return candidate


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scrapers.gmaps.run",
        description="Scrape Google Maps within premium commercial target zones.",
    )

    # ---- City selection -----------------------------------------------
    city_group = p.add_mutually_exclusive_group(required=True)
    city_group.add_argument("--city", choices=ALL_CITIES, help="Run for a single city.")
    city_group.add_argument(
        "--all-cities",
        action="store_true",
        help="Run for every configured city (Medellín + Bogotá).",
    )

    # ---- Category selection ------------------------------------------
    cat_group = p.add_mutually_exclusive_group()
    cat_group.add_argument(
        "--category",
        choices=sorted(CATEGORIES),
        help="Single category slug.",
    )
    cat_group.add_argument(
        "--all-categories",
        action="store_true",
        help="Run all categories (filtered by --priority-max if set).",
    )

    # ---- Zone selection ----------------------------------------------
    p.add_argument(
        "--zone",
        action="append",
        choices=list_all_zone_names(),
        help=(
            "Restrict to one or more named zones (repeat flag). "
            "If omitted, every enabled zone with priority <= --priority-max runs."
        ),
    )
    p.add_argument(
        "--priority-max",
        type=int,
        default=2,
        choices=[1, 2, 3],
        help="Include zones (and categories) with priority <= this. Default 2.",
    )

    # ---- H3 grid options ---------------------------------------------
    p.add_argument(
        "--resolution",
        type=int,
        default=7,
        metavar="R",
        help="Base H3 resolution (default 7).",
    )
    p.add_argument(
        "--max-resolution",
        type=int,
        default=9,
        metavar="R",
        help="Max H3 resolution for saturated-cell subdivision (default 9).",
    )

    # ---- Limits / smoke tests ----------------------------------------
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Cap validated results returned per category.",
    )
    p.add_argument(
        "--limit-hexes",
        type=int,
        default=None,
        metavar="N",
        help="Cap H3 cells searched per (city, category). Useful for smoke tests.",
    )

    # ---- Modes that don't hit the API --------------------------------
    p.add_argument(
        "--dry-run-grid",
        action="store_true",
        help="Print grid stats and exit. No API calls.",
    )
    p.add_argument(
        "--estimate-cost",
        action="store_true",
        help="Print detailed cost estimate and exit. No API calls.",
    )

    # ---- Budget ------------------------------------------------------
    p.add_argument(
        "--budget-cap-usd",
        type=float,
        default=275.0,
        metavar="USD",
        help="Hard-stop budget in USD (default 275).",
    )
    p.add_argument(
        "--force-over-budget",
        action="store_true",
        help="Proceed even if the pre-run estimate exceeds the cap.",
    )

    return p


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve_cities(args: argparse.Namespace) -> list[str]:
    return ALL_CITIES if args.all_cities else [args.city]


def _resolve_categories(args: argparse.Namespace) -> list[str]:
    if args.category:
        return [args.category]
    # default if neither --category nor --all-categories given: priority-filtered set
    return get_categories_by_priority(priority_max=args.priority_max)


def _resolve_cells_per_city(
    args: argparse.Namespace,
) -> dict[str, list[H3Cell]]:
    """Generate (and optionally trim) H3 cells for every selected city."""
    cells_by_city: dict[str, list[H3Cell]] = {}
    for city in _resolve_cities(args):
        cells = generate_target_grid(
            city,
            resolution=args.resolution,
            priority_max=args.priority_max,
            zone_names=args.zone,
        )
        if args.limit_hexes is not None:
            cells = cells[: args.limit_hexes]
        cells_by_city[city] = cells
    return cells_by_city


# ---------------------------------------------------------------------------
# Dry-run grid (no API)
# ---------------------------------------------------------------------------
def _print_grid_summary(cells_by_city: dict[str, list[H3Cell]], categories: list[str]) -> None:
    total_hexes = sum(len(cells) for cells in cells_by_city.values())
    nearby_calls = total_hexes * len(categories)

    print()
    print("=" * 64)
    print("  H3 Grid — Dry-Run")
    print("=" * 64)
    for city, cells in cells_by_city.items():
        canonical = get_city(city).canonical_name
        zones: dict[str, int] = {}
        for c in cells:
            zones[c.zone_name] = zones.get(c.zone_name, 0) + 1
        print(f"  City: {canonical}  ({len(cells)} hexes)")
        for z, n in sorted(zones.items()):
            print(f"    - {z}: {n} hexes")
    print(f"  Total hexes        : {total_hexes}")
    print(f"  Categories         : {len(categories)} ({', '.join(categories)})")
    print(f"  Nearby Search calls: {nearby_calls:,}")
    if total_hexes:
        first_cells = [c for cells in cells_by_city.values() for c in cells][:10]
        print()
        print("  First 10 hex centres:")
        for c in first_cells:
            print(
                f"    {c.cell_id}  city={c.city_slug}  zone={c.zone_name}  "
                f"({c.center_lat:.5f}, {c.center_lng:.5f})"
            )
    print()


def _print_cost_estimate(
    cells_by_city: dict[str, list[H3Cell]],
    categories: list[str],
    cap_usd: float,
) -> dict[str, float]:
    total_hexes = sum(len(cells) for cells in cells_by_city.values())
    nearby_calls = total_hexes * len(categories)
    est = CostTracker.estimate(nearby_calls)

    print("=" * 64)
    print("  Cost Estimate")
    print("=" * 64)
    print(f"  Nearby Search calls : {est['nearby_calls']:,}")
    print(
        f"  Place Details calls : "
        f"{est['details_calls_low']:,} (low) / "
        f"{est['details_calls_mid']:,} (mid) / "
        f"{est['details_calls_high']:,} (high)"
    )
    print(
        f"  Estimated cost USD  : "
        f"${est['cost_low']:.2f} (low) / "
        f"${est['cost_mid']:.2f} (mid) / "
        f"${est['cost_high']:.2f} (high)"
    )
    print(f"  Budget cap          : ${cap_usd:.2f}")
    status = "OK" if est["cost_mid"] <= cap_usd else "OVER BUDGET"
    print(f"  Status              : {status}")

    if est["cost_mid"] > cap_usd:
        prio1 = get_categories_by_priority(priority_max=1)
        print()
        print("  Recommendation:")
        print("    Mid-estimate exceeds budget. Try one of:")
        print(
            f"      1. Run priority-1 categories first ({len(prio1)} total): " f"{', '.join(prio1)}"
        )
        print("      2. Lower --priority-max from 2 to 1.")
        print("      3. Limit zones with --zone or reduce --priority-max.")
        print("      4. Add --force-over-budget if you've authorised more spend.")
    print()
    return est


# ---------------------------------------------------------------------------
# Parquet writers
# ---------------------------------------------------------------------------
def _write_business_parquet(rows: list, path: Path) -> None:
    serialised = [r.model_dump(mode="json") for r in rows]
    df = pl.DataFrame(serialised).with_columns(pl.col("quality_flags").cast(pl.List(pl.Utf8)))
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(str(path))


def _write_evidence_parquet(rows: list, path: Path) -> None:
    if not rows:
        return
    df = pl.DataFrame([asdict(r) for r in rows])
    path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(str(path))


def _write_websites_parquet(businesses: list, path: Path) -> int:
    """Write the Instagram-scraper handoff parquet.

    Schema (consumed by ``scrapers.instagram.scraper.load_seed_from_parquet``):
        source_id, name, city, website, instagram_handle, category_raw

    ``instagram_handle`` is extracted from ``website`` when the URL points to
    instagram.com / instagr.am; otherwise it's null. Rows with neither a
    website nor an instagram_handle are skipped.
    """
    website_rows = []
    for b in businesses:
        ig_handle = extract_instagram_handle(b.website)
        # Keep the row if it has either an extractable IG handle OR any website
        # (Leo's loader filters to non-null instagram_handle, but we preserve
        # the website column for future direct-handle extraction)
        if not b.website and not ig_handle:
            continue
        website_rows.append(
            {
                "source_id": b.source_id,
                "name": b.name,
                "city": b.city,
                "website": b.website,
                "instagram_handle": ig_handle,
                "category_raw": getattr(b, "category_raw", None),
            }
        )
    if not website_rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(website_rows).write_parquet(str(path))
    return len(website_rows)


def regenerate_websites_handoff(
    raw_paths: list[Path] | None = None,
    out_path: Path = Path("data/interim/gmaps_websites.parquet"),
) -> int:
    """Rebuild the Instagram handoff parquet from existing raw gmaps parquets.

    Useful when the scrape has already run and we just need to add new
    columns (instagram_handle, category_raw) without re-paying the API cost.
    """
    if raw_paths is None:
        raw_paths = [
            Path("data/raw/gmaps/medellin.parquet"),
            Path("data/raw/gmaps/bogota.parquet"),
        ]

    rows: list[dict] = []
    for p in raw_paths:
        if not p.exists():
            logger.warning(f"Skipping missing parquet: {p}")
            continue
        df = pl.read_parquet(p)
        for r in df.iter_rows(named=True):
            website = r.get("website")
            ig_handle = extract_instagram_handle(website)
            if not website and not ig_handle:
                continue
            rows.append(
                {
                    "source_id": r["source_id"],
                    "name": r["name"],
                    "city": r["city"],
                    "website": website,
                    "instagram_handle": ig_handle,
                    "category_raw": r.get("category_raw"),
                }
            )

    if not rows:
        logger.warning("No website rows found — handoff parquet not written.")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_parquet(str(out_path))
    n_with_handle = sum(1 for r in rows if r["instagram_handle"])
    logger.info(f"Wrote {len(rows)} rows → {out_path} " f"({n_with_handle} with instagram_handle)")
    return len(rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    cities = _resolve_cities(args)
    categories = _resolve_categories(args)
    cells_by_city = _resolve_cells_per_city(args)

    # ---- No-API modes ------------------------------------------------
    if args.dry_run_grid:
        _print_grid_summary(cells_by_city, categories)
        _print_cost_estimate(cells_by_city, categories, args.budget_cap_usd)
        return 0

    if args.estimate_cost:
        _print_grid_summary(cells_by_city, categories)
        _print_cost_estimate(cells_by_city, categories, args.budget_cap_usd)
        return 0

    # ---- Pre-flight budget guard ------------------------------------
    total_hexes = sum(len(cells) for cells in cells_by_city.values())
    nearby_calls = total_hexes * len(categories)
    estimate = CostTracker.estimate(nearby_calls)
    try:
        assert_within_budget(estimate, args.budget_cap_usd, force=args.force_over_budget)
    except BudgetEstimateExceededError as exc:
        logger.error(str(exc))
        _print_cost_estimate(cells_by_city, categories, args.budget_cap_usd)
        return 1

    logger.info(
        f"Pre-flight estimate: ${estimate['cost_mid']:.2f} mid "
        f"(low ${estimate['cost_low']:.2f} / high ${estimate['cost_high']:.2f}) "
        f"vs cap ${args.budget_cap_usd:.2f}"
    )

    # ---- Real scrape -------------------------------------------------
    cost_tracker = CostTracker(cap_usd=args.budget_cap_usd)
    seen_place_ids: set[str] = set()  # SHARED across cities + categories

    all_businesses: list = []
    all_evidence: list = []
    per_city_results: dict[str, list] = {city: [] for city in cities}

    budget_hit = False

    for city in cities:
        cells = cells_by_city[city]
        if not cells:
            logger.warning(f"No cells for city={city!r} — skipping.")
            continue

        for cat in categories:
            logger.info(f"=== {city} :: {cat} ===")
            try:
                businesses, evidence = scrape_cells_for_category(
                    cells,
                    cat,
                    cost_tracker=cost_tracker,
                    seen_place_ids=seen_place_ids,
                    max_resolution=args.max_resolution,
                    limit=args.limit,
                )
            except BudgetExceededError as exc:
                logger.error(f"Budget cap reached during {city}/{cat}: {exc}")
                budget_hit = True
                break
            except Exception as exc:  # noqa: BLE001
                logger.error(f"{city}/{cat} failed: {exc}")
                continue

            if businesses:
                cat_path = Path(f"data/raw/gmaps/{city}_{cat}.parquet")
                _write_business_parquet(businesses, cat_path)
                logger.info(f"Wrote {len(businesses)} rows -> {cat_path}")
                per_city_results[city].extend(businesses)
                all_businesses.extend(businesses)
            if evidence:
                all_evidence.extend(evidence)

        if budget_hit:
            break

    # ---- City-level dedup + outputs ----------------------------------
    for city, biz_list in per_city_results.items():
        if not biz_list:
            continue
        seen_local: set[str] = set()
        deduped = []
        for biz in biz_list:
            if biz.source_id not in seen_local:
                seen_local.add(biz.source_id)
                deduped.append(biz)
        _write_business_parquet(deduped, Path(f"data/raw/gmaps/{city}.parquet"))

    # ---- Cross-city handoffs -----------------------------------------
    if all_businesses:
        n_websites = _write_websites_parquet(
            all_businesses, Path("data/interim/gmaps_websites.parquet")
        )
    else:
        n_websites = 0

    if all_evidence:
        _write_evidence_parquet(all_evidence, Path("data/interim/gmaps_place_categories.parquet"))

    # ---- Final report ------------------------------------------------
    print()
    print("=" * 64)
    print("  GMaps scrape — summary")
    print("=" * 64)
    print(f"  Cities          : {', '.join(cities)}")
    print(
        f"  Categories      : {len(categories)} "
        f"(priority<={args.priority_max}): {', '.join(categories)}"
    )
    print(f"  Total hexes     : {total_hexes}")
    print(f"  Unique businesses: {len(all_businesses)}")
    print(f"  Evidence rows   : {len(all_evidence)}")
    print(f"  With websites   : {n_websites}")
    print(f"  Cost actual     : {cost_tracker.summary()}")
    print(f"  Budget cap      : ${args.budget_cap_usd:.2f}")
    if budget_hit:
        print("  WARNING: budget cap reached, scrape stopped early.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
