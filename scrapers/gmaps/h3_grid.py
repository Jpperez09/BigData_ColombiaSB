"""H3 hexagonal grid generation for premium commercial target zones.

Each cell carries metadata (city, zone_name, priority, resolution, centre)
so the scraper can attribute every API call to a budget bucket and so we can
log evidence per (place_id, city, zone, category) tuple.

Resolution defaults:
  7 (~5 km², edge ~1.2 km) — default base grid (cheap, good city coverage).
  8 (~0.7 km², edge ~0.46 km) — adaptive subdivision when a cell saturates.
  9 (~0.1 km², edge ~0.17 km) — second-level subdivision for very dense cells.
"""

from __future__ import annotations

from dataclasses import dataclass

import h3
from loguru import logger

from scrapers.gmaps.target_zones import TargetZone, get_zones

# Per-resolution Nearby Search radius (metres). Sized so adjacent cell
# circles overlap slightly, leaving no gaps along zone boundaries.
_RESOLUTION_RADIUS: dict[int, int] = {
    7: 1500,
    8: 800,
    9: 400,
    10: 200,
}


@dataclass(frozen=True)
class H3Cell:
    """An H3 cell tagged with the zone and city it covers."""

    cell_id: str
    city_slug: str
    zone_name: str
    resolution: int
    center_lat: float
    center_lng: float
    priority: int


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def radius_for_resolution(resolution: int) -> int:
    """Return the Nearby Search radius (metres) for an H3 resolution."""
    if resolution in _RESOLUTION_RADIUS:
        return _RESOLUTION_RADIUS[resolution]
    return max(100, int(1500 / (2 ** (resolution - 7))))


def get_hex_center(cell_id: str) -> tuple[float, float]:
    """Return the ``(lat, lng)`` centre of an H3 cell."""
    lat, lng = h3.cell_to_latlng(cell_id)
    return lat, lng


def subdivide_cell(cell_id: str, child_resolution: int) -> list[str]:
    """Return sorted child cell IDs at the given resolution."""
    children: set[str] = h3.cell_to_children(cell_id, child_resolution)
    return sorted(children)


# ---------------------------------------------------------------------------
# Grid generation
# ---------------------------------------------------------------------------


def _zone_to_cells(zone: TargetZone, city_slug: str, resolution: int) -> list[H3Cell]:
    """Fill a single zone polygon with H3 cells at the requested resolution."""
    poly = h3.LatLngPoly(zone.polygon)
    cell_ids = h3.h3shape_to_cells(poly, resolution)

    # Edge case: very small polygons may produce zero cells at low resolution.
    # Fall back to the cell containing the polygon centroid.
    if not cell_ids:
        lat = sum(p[0] for p in zone.polygon) / len(zone.polygon)
        lng = sum(p[1] for p in zone.polygon) / len(zone.polygon)
        cell_ids = {h3.latlng_to_cell(lat, lng, resolution)}

    out: list[H3Cell] = []
    for cell_id in sorted(cell_ids):
        lat, lng = h3.cell_to_latlng(cell_id)
        out.append(
            H3Cell(
                cell_id=cell_id,
                city_slug=city_slug,
                zone_name=zone.name,
                resolution=resolution,
                center_lat=lat,
                center_lng=lng,
                priority=zone.priority,
            )
        )
    return out


def generate_target_grid(
    city_slug: str,
    resolution: int = 7,
    priority_max: int = 2,
    zone_names: list[str] | None = None,
) -> list[H3Cell]:
    """Build a deterministic, sorted list of H3 cells for the city's enabled zones.

    Args:
        city_slug:    ``"medellin"`` or ``"bogota"``.
        resolution:   Base H3 resolution (default 7).
        priority_max: Only include zones with priority <= this. Default 2.
        zone_names:   Optional explicit zone allow-list.

    Returns:
        Sorted list of ``H3Cell`` (key: priority, zone_name, cell_id).
    """
    zones = get_zones(city_slug, priority_max=priority_max, zone_names=zone_names)
    cells: list[H3Cell] = []

    for zone in zones:
        zone_cells = _zone_to_cells(zone, city_slug, resolution)
        cells.extend(zone_cells)
        logger.debug(
            f"Zone {zone.name!r} city={city_slug} priority={zone.priority} "
            f"cells={len(zone_cells)}"
        )

    cells.sort(key=lambda c: (c.priority, c.zone_name, c.cell_id))
    logger.info(
        f"Grid: city={city_slug!r} resolution={resolution} "
        f"priority_max={priority_max} zones={len(zones)} cells={len(cells)}"
    )
    return cells
