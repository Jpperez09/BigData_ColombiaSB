"""Priority SMB categories for the Colombian market, mapped to Google Places keywords.

Each category has a priority:
  1 — must-scrape verticals (highest WhatsApp/AI fit, dense in target zones).
  2 — secondary verticals; include when the budget allows.

If a budget estimate exceeds the cap, the runner recommends running priority-1
categories first and priority-2 separately rather than silently skipping any.
"""

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

# Verticals where chat-based sales / service are highest-value and most common.
CATEGORY_PRIORITY: dict[str, int] = {
    # Priority 1 — top WhatsApp/AI fit, dense in premium commercial zones
    "restaurants": 1,
    "beauty_salons": 1,
    "clothing_stores": 1,
    "dental_clinics": 1,
    "gyms": 1,
    "real_estate": 1,
    "bakeries": 1,
    "jewelry_stores": 1,
    "optical_stores": 1,
    # Priority 2 — secondary verticals
    "veterinarians": 2,
    "photographers": 2,
    "language_schools": 2,
    "tutoring_centers": 2,
    "cleaning_services": 2,
    "auto_repair": 2,
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


def get_categories_by_priority(priority_max: int = 2) -> list[str]:
    """Return category slugs with priority <= ``priority_max``, sorted by priority.

    Within the same priority, slugs are returned in alphabetical order so the
    output is deterministic.
    """
    selected = [slug for slug, prio in CATEGORY_PRIORITY.items() if prio <= priority_max]
    return sorted(selected, key=lambda s: (CATEGORY_PRIORITY[s], s))
