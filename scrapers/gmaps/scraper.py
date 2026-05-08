"""H3-grid + target-zone orchestration for the Google Maps spider.

Architecture:

    scrape_cells_for_category(cells, category_slug, ..., seen_place_ids, cost_tracker)
        |
        +-- iterates H3 cells (already tagged with city + zone + priority)
        +-- subdivides saturated cells (>=60 results) up to max_resolution
        +-- shares ``seen_place_ids`` across categories so we never pay for
            Place Details twice
        +-- emits CategoryEvidence rows so we don't lose category data
            when a place_id is deduped across categories

The thin convenience wrapper ``scrape_gmaps_city_category`` exists for callers
that want single-city / single-category behaviour. ``run.py`` orchestrates the
full multi-city, multi-category, shared-state production run.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from loguru import logger
from pydantic import ValidationError

from scrapers.gmaps.categories import get_keyword
from scrapers.gmaps.cities import get_city
from scrapers.gmaps.client import GMapsClient
from scrapers.gmaps.cost import BudgetExceededError, CostTracker
from scrapers.gmaps.h3_grid import (
    H3Cell,
    generate_target_grid,
    get_hex_center,
    radius_for_resolution,
    subdivide_cell,
)
from scrapers.gmaps.normalize import google_place_to_business_raw
from utils.models import BusinessRaw

# Polite delay between consecutive Place Details calls (seconds).
_DETAILS_SLEEP = 0.2

# Google Nearby Search result cap — treat a full page as a saturated cell.
_SATURATION_THRESHOLD = 60


# ---------------------------------------------------------------------------
# Evidence model — records that ``place_id`` was found in this category
# at this cell, even if its Place Details were already fetched earlier.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CategoryEvidence:
    place_id: str
    city: str
    zone_name: str
    category: str
    h3_cell: str


# ---------------------------------------------------------------------------
# Per-call state container (avoids threading mutable counters through recursion)
# ---------------------------------------------------------------------------
@dataclass
class _ScrapeState:
    results: list[BusinessRaw] = field(default_factory=list)
    evidence: list[CategoryEvidence] = field(default_factory=list)
    skipped: int = 0


# ---------------------------------------------------------------------------
# Recursive cell search
# ---------------------------------------------------------------------------
def _search_cell(
    *,
    client: GMapsClient,
    cost: CostTracker,
    keyword: str,
    category_slug: str,
    cell: H3Cell,
    cell_id: str,
    resolution: int,
    max_resolution: int,
    seen_place_ids: set[str],
    state: _ScrapeState,
    limit: int | None,
) -> None:
    """Search one H3 cell; subdivide if saturated; write results/evidence into *state*."""
    if limit is not None and len(state.results) >= limit:
        return

    lat, lng = get_hex_center(cell_id)
    radius = radius_for_resolution(resolution)

    raw_places = client.nearby_search((lat, lng), radius, keyword)
    cost.record_nearby_search(city=cell.city_slug, zone=cell.zone_name, category=category_slug)

    # Saturation: subdivide and re-query children rather than processing this cell.
    if len(raw_places) >= _SATURATION_THRESHOLD and resolution < max_resolution:
        children = subdivide_cell(cell_id, resolution + 1)
        logger.info(
            f"Saturated cell — city={cell.city_slug} zone={cell.zone_name} "
            f"category={category_slug} parent={cell_id} resolution={resolution} "
            f"results={len(raw_places)} children={len(children)} "
            f"reason=hit_60_result_cap"
        )
        for child_id in children:
            if limit is not None and len(state.results) >= limit:
                return
            _search_cell(
                client=client,
                cost=cost,
                keyword=keyword,
                category_slug=category_slug,
                cell=cell,
                cell_id=child_id,
                resolution=resolution + 1,
                max_resolution=max_resolution,
                seen_place_ids=seen_place_ids,
                state=state,
                limit=limit,
            )
        return

    # Normal case: record evidence + fetch details for previously-unseen places.
    for place in raw_places:
        if limit is not None and len(state.results) >= limit:
            return

        place_id: str = place.get("place_id", "")
        if not place_id:
            continue

        # Always record the (place, category, cell) tuple — even if dedup skips fetch.
        state.evidence.append(
            CategoryEvidence(
                place_id=place_id,
                city=cell.city_slug,
                zone_name=cell.zone_name,
                category=category_slug,
                h3_cell=cell_id,
            )
        )

        # Cross-category dedup: skip Place Details if we already paid for it.
        if place_id in seen_place_ids:
            continue
        seen_place_ids.add(place_id)

        time.sleep(_DETAILS_SLEEP)
        try:
            details = client.place_details(place_id)
            cost.record_place_details(
                city=cell.city_slug, zone=cell.zone_name, category=category_slug
            )
            city_canonical = get_city(cell.city_slug).canonical_name
            business = google_place_to_business_raw(place, details, city_canonical)
            state.results.append(business)
            logger.debug(f"OK  {place_id}  {business.name!r}")
        except ValidationError as exc:
            state.skipped += 1
            logger.warning(f"Validation failed for {place_id}: {exc}")
        except BudgetExceededError:
            raise
        except Exception as exc:  # noqa: BLE001
            state.skipped += 1
            logger.error(f"Unexpected error for {place_id}: {exc}")


# ---------------------------------------------------------------------------
# Public API — primitive (cells already generated by the orchestrator)
# ---------------------------------------------------------------------------
def scrape_cells_for_category(
    cells: list[H3Cell],
    category_slug: str,
    *,
    cost_tracker: CostTracker,
    seen_place_ids: set[str],
    max_resolution: int = 9,
    limit: int | None = None,
) -> tuple[list[BusinessRaw], list[CategoryEvidence]]:
    """Scrape one category over a pre-generated set of H3 cells.

    Args:
        cells:           H3 cells (with city/zone metadata) to search.
        category_slug:   Key from ``CATEGORIES``.
        cost_tracker:    Shared CostTracker — must be passed in.
        seen_place_ids:  SHARED dedup set — must be passed in. Any place_id
                         already present is treated as already-fetched and
                         we skip Place Details for it.
        max_resolution:  Max H3 resolution for saturation subdivision.
        limit:           Cap on validated results returned (None = no cap).

    Returns:
        (businesses, evidence_rows)

    Raises:
        BudgetExceededError: When the cost cap is hit; caller should catch.
    """
    keyword = get_keyword(category_slug)
    client = GMapsClient()
    state = _ScrapeState()

    logger.info(
        f"Scraping category={category_slug!r} keyword={keyword!r} "
        f"cells={len(cells)} | seen_so_far={len(seen_place_ids)}"
    )

    for i, cell in enumerate(cells, 1):
        if limit is not None and len(state.results) >= limit:
            break
        logger.debug(
            f"Cell {i}/{len(cells)}: {cell.cell_id} "
            f"zone={cell.zone_name} priority={cell.priority}"
        )
        try:
            _search_cell(
                client=client,
                cost=cost_tracker,
                keyword=keyword,
                category_slug=category_slug,
                cell=cell,
                cell_id=cell.cell_id,
                resolution=cell.resolution,
                max_resolution=max_resolution,
                seen_place_ids=seen_place_ids,
                state=state,
                limit=limit,
            )
        except BudgetExceededError as exc:
            logger.error(str(exc))
            raise

    logger.info(
        f"Done category={category_slug!r}: {len(state.results)} new, "
        f"{state.skipped} skipped, {len(state.evidence)} evidence rows | "
        f"cost: {cost_tracker.summary()}"
    )
    return state.results, state.evidence


# ---------------------------------------------------------------------------
# Convenience wrapper — single city, single category
# ---------------------------------------------------------------------------
def scrape_gmaps_city_category(
    city_slug: str,
    category_slug: str,
    *,
    resolution: int = 7,
    max_resolution: int = 9,
    priority_max: int = 2,
    zone_names: list[str] | None = None,
    limit: int | None = None,
    limit_hexes: int | None = None,
    cost_tracker: CostTracker | None = None,
    seen_place_ids: set[str] | None = None,
) -> list[BusinessRaw]:
    """Scrape one city + one category through the target-zone H3 grid.

    Args:
        city_slug:       ``"medellin"`` or ``"bogota"``.
        category_slug:   Key from ``CATEGORIES``.
        resolution:      Base H3 resolution (default 7).
        max_resolution:  Max H3 resolution for saturation subdivision (default 9).
        priority_max:    Include zones with priority <= this. Default 2.
        zone_names:      Optional explicit zone allow-list.
        limit:           Cap on validated results returned.
        limit_hexes:     Cap on hex cells searched (smoke tests).
        cost_tracker:    Shared CostTracker; created fresh if None.
        seen_place_ids:  Shared dedup set; created fresh if None.

    Returns:
        List of validated ``BusinessRaw`` instances. Evidence rows are dropped
        in this convenience wrapper — for production runs use
        ``scrape_cells_for_category`` directly.
    """
    # Validate city slug exists (raises KeyError if not).
    get_city(city_slug)

    cells = generate_target_grid(
        city_slug,
        resolution=resolution,
        priority_max=priority_max,
        zone_names=zone_names,
    )
    if limit_hexes is not None:
        cells = cells[:limit_hexes]

    if cost_tracker is None:
        cost_tracker = CostTracker()
    if seen_place_ids is None:
        seen_place_ids = set()

    try:
        businesses, _evidence = scrape_cells_for_category(
            cells,
            category_slug,
            cost_tracker=cost_tracker,
            seen_place_ids=seen_place_ids,
            max_resolution=max_resolution,
            limit=limit,
        )
    except BudgetExceededError:
        # Single-category convenience wrapper swallows the budget error
        # and returns whatever has been collected so far.
        return []
    return businesses
