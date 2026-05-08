"""Thin wrapper around googlemaps.Client with retry / back-off.

Billing note: Place Details charges per field category —
  Basic fields  (name, address, geometry, types): cheapest tier
  Contact fields (phone, website):                medium tier
  Atmosphere fields (rating, reviews_count):      premium tier
We request only the fields we actually map in normalize.py.
Add cost-tracking instrumentation here once the project scales.
"""

from __future__ import annotations

import functools
from typing import Any

import googlemaps
from googlemaps.exceptions import ApiError, Timeout, TransportError
from loguru import logger
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from utils.config import get_settings

# Fields requested in every Place Details call — keep this list minimal.
_DETAIL_FIELDS = [
    "place_id",
    "name",
    "formatted_address",
    "vicinity",
    "geometry",
    "formatted_phone_number",
    "international_phone_number",
    "rating",
    "user_ratings_total",
    "type",
    "website",
]


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient errors that warrant a retry."""
    if isinstance(exc, (TransportError, Timeout)):
        return True
    if isinstance(exc, ApiError):
        return getattr(exc, "status", "") in ("OVER_QUERY_LIMIT", "UNKNOWN_ERROR")
    return False


@functools.lru_cache(maxsize=1)
def _build_raw_client() -> googlemaps.Client:
    """Instantiate the googlemaps.Client singleton (cached).

    Raises:
        RuntimeError: If GOOGLE_MAPS_API_KEY is not configured.
    """
    key = get_settings().GOOGLE_MAPS_API_KEY
    if not key:
        raise RuntimeError("GOOGLE_MAPS_API_KEY is not set. Add it to your .env file.")
    return googlemaps.Client(key=key)


class GMapsClient:
    """Facade over googlemaps.Client for Nearby Search + Place Details.

    Both methods apply exponential back-off on transient failures and
    rate-limit responses from the Google API.
    """

    def __init__(self) -> None:
        self._client = _build_raw_client()

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def nearby_search(
        self,
        location: tuple[float, float],
        radius_m: int,
        keyword: str,
    ) -> list[dict[str, Any]]:
        """Call Places Nearby Search and return the raw results list.

        Returns at most 20 results (one page). Pagination is not implemented.

        Args:
            location: ``(lat, lng)`` tuple for the search centre.
            radius_m:  Search radius in metres.
            keyword:   Google Places keyword (e.g. ``"restaurante"``).
        """
        logger.debug(f"Nearby search: keyword={keyword!r} radius={radius_m}m")
        response = self._client.places_nearby(
            location=location,
            radius=radius_m,
            keyword=keyword,
        )
        results: list[dict[str, Any]] = response.get("results", [])
        logger.debug(f"Nearby search: {len(results)} result(s)")
        return results

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def place_details(self, place_id: str) -> dict[str, Any]:
        """Fetch Place Details for a single place_id.

        Args:
            place_id: Google Maps ``place_id`` string.

        Returns:
            The ``result`` dict from the Place Details response,
            or an empty dict if the API returns nothing.
        """
        logger.debug(f"Place details: place_id={place_id}")
        response = self._client.place(
            place_id=place_id,
            fields=_DETAIL_FIELDS,
        )
        return response.get("result", {})
