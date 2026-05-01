"""City configurations for the GMaps scraper.

Canonical city names must match exactly the values accepted by BusinessRaw:
``"Medellín"`` and ``"Bogotá"``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CityConfig:
    """Static configuration for a scrape-target city."""

    slug: str
    canonical_name: str  # must match BusinessRaw city constraint
    center_lat: float
    center_lng: float


CITIES: dict[str, CityConfig] = {
    "medellin": CityConfig(
        slug="medellin",
        canonical_name="Medellín",
        center_lat=6.2442,
        center_lng=-75.5812,
    ),
    "bogota": CityConfig(
        slug="bogota",
        canonical_name="Bogotá",
        center_lat=4.7110,
        center_lng=-74.0721,
    ),
}


def get_city(slug: str) -> CityConfig:
    """Return the CityConfig for a city slug.

    Args:
        slug: ``"medellin"`` or ``"bogota"``.

    Raises:
        KeyError: If ``slug`` is not in CITIES.
    """
    if slug not in CITIES:
        valid = ", ".join(sorted(CITIES))
        raise KeyError(f"Unknown city slug {slug!r}. Valid slugs: {valid}")
    return CITIES[slug]
