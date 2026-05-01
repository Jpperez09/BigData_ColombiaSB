"""High-level orchestration for a single city + category scrape run.

One call to ``scrape_gmaps_city_category`` performs:
  1. One Nearby Search request (up to 20 results, no pagination yet).
  2. One Place Details request per unique place_id.
  3. Normalisation + BusinessRaw validation for every result.

H3 grid coverage and multi-page pagination are left for a future iteration.
"""

from __future__ import annotations

import time

from loguru import logger
from pydantic import ValidationError

from scrapers.gmaps.categories import get_keyword
from scrapers.gmaps.cities import get_city
from scrapers.gmaps.client import GMapsClient
from scrapers.gmaps.normalize import google_place_to_business_raw
from utils.models import BusinessRaw

# Polite delay between consecutive Place Details calls (seconds).
_DETAILS_SLEEP = 0.2


def scrape_gmaps_city_category(
    city_slug: str,
    category_slug: str,
    radius_m: int = 1000,
    limit: int | None = None,
) -> list[BusinessRaw]:
    """Scrape Google Maps for businesses matching a city and category.

    Args:
        city_slug:     ``"medellin"`` or ``"bogota"``.
        category_slug: Key from ``scrapers.gmaps.categories.CATEGORIES``.
        radius_m:      Search radius in metres around the city centre.
        limit:         Cap on the number of validated results returned.
                       ``None`` means return all results (≤ 20 per page).

    Returns:
        List of validated ``BusinessRaw`` instances, deduplicated by place_id.
    """
    city = get_city(city_slug)
    keyword = get_keyword(category_slug)
    client = GMapsClient()

    logger.info(
        f"Scraping: city={city.canonical_name!r} "
        f"category={category_slug!r} keyword={keyword!r} "
        f"radius={radius_m}m"
    )

    location = (city.center_lat, city.center_lng)
    raw_places = client.nearby_search(location, radius_m, keyword)

    seen_ids: set[str] = set()
    results: list[BusinessRaw] = []
    skipped = 0

    for place in raw_places:
        if limit is not None and len(results) >= limit:
            break

        place_id: str = place.get("place_id", "")
        if not place_id or place_id in seen_ids:
            continue
        seen_ids.add(place_id)

        time.sleep(_DETAILS_SLEEP)

        try:
            details = client.place_details(place_id)
            business = google_place_to_business_raw(place, details, city.canonical_name)
            results.append(business)
            logger.debug(f"OK  {place_id}  {business.name!r}")
        except ValidationError as exc:
            skipped += 1
            logger.warning(f"Validation failed for {place_id}: {exc}")
        except Exception as exc:  # noqa: BLE001
            skipped += 1
            logger.error(f"Unexpected error for {place_id}: {exc}")

    logger.info(
        f"Done: {len(results)} valid, {skipped} skipped " f"(from {len(raw_places)} nearby results)"
    )
    return results
