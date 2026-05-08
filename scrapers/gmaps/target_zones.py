"""Premium commercial target zones for the GMaps scraper.

Rather than scraping whole municipalities, we generate H3 cells only inside
small named polygons that cover commercially active corridors. This keeps the
Google Maps API budget focused on prospect-rich areas where SMBs are likely
to (a) have meaningful customer volume, (b) use WhatsApp/Instagram/websites,
and (c) afford a premium AI sales agent.

Each zone has:
  name     -- machine-readable identifier (snake_case)
  priority -- 1 (always run), 2 (run if budget allows), 3 (off by default)
  enabled  -- master switch, lets you keep a zone definition without running it
  polygon  -- list of (lat, lng) vertices forming the outer ring

Polygons here are first-pass bounding boxes drawn from public maps. Refine
them with proper GeoJSON when available — keep the structure intact.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TargetZone:
    """A named commercial target area."""

    name: str
    priority: int
    enabled: bool
    polygon: list[tuple[float, float]]


def _bbox_poly(
    lat_min: float, lat_max: float, lng_min: float, lng_max: float
) -> list[tuple[float, float]]:
    """Convert an axis-aligned bounding box into a 4-vertex polygon."""
    return [
        (lat_max, lng_min),  # NW
        (lat_max, lng_max),  # NE
        (lat_min, lng_max),  # SE
        (lat_min, lng_min),  # SW
    ]


# ---------------------------------------------------------------------------
# Target zone definitions
# ---------------------------------------------------------------------------
TARGET_ZONES: dict[str, list[TargetZone]] = {
    "medellin": [
        # ---- Priority 1 — top commercial corridors -------------------------
        TargetZone(
            name="el_poblado_provenza_lleras",
            priority=1,
            enabled=True,
            polygon=_bbox_poly(6.190, 6.225, -75.585, -75.555),
        ),
        TargetZone(
            name="ciudad_del_rio",
            priority=1,
            enabled=True,
            polygon=_bbox_poly(6.214, 6.225, -75.583, -75.572),
        ),
        TargetZone(
            name="laureles",
            priority=1,
            enabled=True,
            polygon=_bbox_poly(6.240, 6.258, -75.605, -75.585),
        ),
        TargetZone(
            name="estadio_los_colores",
            priority=1,
            enabled=True,
            polygon=_bbox_poly(6.252, 6.270, -75.598, -75.575),
        ),
        TargetZone(
            name="envigado_zona_viva",
            priority=1,
            enabled=True,
            polygon=_bbox_poly(6.158, 6.184, -75.600, -75.572),
        ),
        TargetZone(
            name="sabaneta_parque_mayorca",
            priority=1,
            enabled=True,
            polygon=_bbox_poly(6.140, 6.160, -75.625, -75.602),
        ),
        # ---- Priority 2 — secondary commercial corridors -------------------
        TargetZone(
            name="belen_rosales",
            priority=2,
            enabled=True,
            polygon=_bbox_poly(6.218, 6.238, -75.615, -75.594),
        ),
        # ---- Priority 3 — off by default -----------------------------------
        TargetZone(
            name="itagui_commercial",
            priority=3,
            enabled=False,
            polygon=_bbox_poly(6.165, 6.180, -75.620, -75.600),
        ),
        TargetZone(
            name="rionegro_llanogrande",
            priority=3,
            enabled=False,
            polygon=_bbox_poly(6.140, 6.180, -75.395, -75.355),
        ),
    ],
    "bogota": [
        # ---- Priority 1 — top commercial corridors -------------------------
        TargetZone(
            name="parque_93_chico_virrey",
            priority=1,
            enabled=True,
            polygon=_bbox_poly(4.670, 4.685, -74.060, -74.040),
        ),
        TargetZone(
            name="zona_t_andino_retiro",
            priority=1,
            enabled=True,
            polygon=_bbox_poly(4.660, 4.673, -74.058, -74.045),
        ),
        TargetZone(
            name="rosales_nogal",
            priority=1,
            enabled=True,
            polygon=_bbox_poly(4.655, 4.670, -74.045, -74.028),
        ),
        TargetZone(
            name="usaquen_santa_barbara",
            priority=1,
            enabled=True,
            polygon=_bbox_poly(4.692, 4.710, -74.045, -74.025),
        ),
        TargetZone(
            name="unicentro_cedritos",
            priority=1,
            enabled=True,
            polygon=_bbox_poly(4.700, 4.735, -74.052, -74.028),
        ),
        TargetZone(
            name="chapinero_alto_zona_g",
            priority=1,
            enabled=True,
            polygon=_bbox_poly(4.638, 4.660, -74.072, -74.052),
        ),
        TargetZone(
            name="quinta_camacho_chapinero_central",
            priority=1,
            enabled=True,
            polygon=_bbox_poly(4.640, 4.658, -74.072, -74.058),
        ),
        # ---- Priority 2 — secondary commercial corridors -------------------
        TargetZone(
            name="salitre_ciudad_empresarial",
            priority=2,
            enabled=True,
            polygon=_bbox_poly(4.650, 4.675, -74.105, -74.075),
        ),
        TargetZone(
            name="la_castellana_pasadena",
            priority=2,
            enabled=True,
            polygon=_bbox_poly(4.685, 4.708, -74.085, -74.063),
        ),
        TargetZone(
            name="colina_campestre_parque_la_colina",
            priority=2,
            enabled=True,
            polygon=_bbox_poly(4.720, 4.745, -74.075, -74.052),
        ),
        TargetZone(
            name="modelia_commercial",
            priority=2,
            enabled=True,
            polygon=_bbox_poly(4.665, 4.685, -74.128, -74.108),
        ),
        # ---- Priority 3 — off by default -----------------------------------
        TargetZone(
            name="fontibon_commercial",
            priority=3,
            enabled=False,
            polygon=_bbox_poly(4.668, 4.685, -74.150, -74.130),
        ),
        TargetZone(
            name="teusaquillo_parkway",
            priority=3,
            enabled=False,
            polygon=_bbox_poly(4.628, 4.650, -74.080, -74.062),
        ),
    ],
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------
def get_zones(
    city_slug: str,
    priority_max: int = 2,
    only_enabled: bool = True,
    zone_names: list[str] | None = None,
) -> list[TargetZone]:
    """Return zones for a city filtered by priority / enabled / name list.

    Args:
        city_slug:    "medellin" or "bogota".
        priority_max: Include zones with priority <= this. Default 2.
        only_enabled: If True, drop zones whose ``enabled`` flag is False.
        zone_names:   If set, restrict to zones whose name is in this list
                      (priority + enabled filters still apply unless explicitly
                      relaxed by setting priority_max high enough).

    Raises:
        KeyError: If ``city_slug`` is unknown.
    """
    if city_slug not in TARGET_ZONES:
        valid = ", ".join(sorted(TARGET_ZONES))
        raise KeyError(f"Unknown city {city_slug!r}. Valid: {valid}")

    zones = list(TARGET_ZONES[city_slug])
    if zone_names is not None:
        wanted = set(zone_names)
        zones = [z for z in zones if z.name in wanted]
    if only_enabled:
        zones = [z for z in zones if z.enabled]
    zones = [z for z in zones if z.priority <= priority_max]
    return zones


def list_all_zone_names(city_slug: str | None = None) -> list[str]:
    """Return every zone name (across all cities, or one), sorted."""
    if city_slug is not None:
        return sorted(z.name for z in TARGET_ZONES.get(city_slug, []))
    return sorted({z.name for zones in TARGET_ZONES.values() for z in zones})
