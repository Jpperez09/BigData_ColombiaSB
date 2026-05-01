"""Priority SMB categories for the Colombian market, mapped to Google Places keywords."""

from __future__ import annotations

# slug -> Spanish keyword sent to the Places Nearby Search API
CATEGORIES: dict[str, str] = {
    "restaurants": "restaurante",
    "clothing_stores": "tienda de ropa",
    "beauty_salons": "salón de belleza",
    "gyms": "gimnasio",
    "dental_clinics": "clínica dental",
    "veterinarians": "veterinaria",
    "real_estate": "inmobiliaria",
    "photographers": "fotógrafo",
    "bakeries": "panadería",
    "jewelry_stores": "joyería",
    "optical_stores": "óptica",
    "auto_repair": "taller mecánico",
    "cleaning_services": "empresa de aseo",
    "language_schools": "academia de idiomas",
    "tutoring_centers": "centro de tutorías",
}


def get_keyword(slug: str) -> str:
    """Return the Google Places search keyword for a category slug.

    Args:
        slug: One of the keys in CATEGORIES (e.g. ``"restaurants"``).

    Raises:
        KeyError: If ``slug`` is not in CATEGORIES.
    """
    if slug not in CATEGORIES:
        valid = ", ".join(sorted(CATEGORIES))
        raise KeyError(f"Unknown category {slug!r}. Valid slugs: {valid}")
    return CATEGORIES[slug]
