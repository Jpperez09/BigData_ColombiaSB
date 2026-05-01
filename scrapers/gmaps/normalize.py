"""Normalise raw Google Places API dicts into validated BusinessRaw instances."""

from __future__ import annotations

import re
from typing import Any

import phonenumbers
from loguru import logger

from utils.models import BusinessRaw, SourceName

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_INSTAGRAM_RE = re.compile(r"instagram\.com/([A-Za-z0-9_.]+)/?", re.IGNORECASE)

_WHATSAPP_KEYWORDS = ("wa.me", "whatsapp", "api.whatsapp.com")

# Google returns these on almost every place — filter them out for category_raw
_GENERIC_TYPES = frozenset(
    {
        "point_of_interest",
        "establishment",
        "food",
        "health",
        "store",
        "premise",
        "subpremise",
        "geocode",
        "street_address",
    }
)

# Instagram path segments that are not real handles
_IG_RESERVED = frozenset({"p", "explore", "accounts", "reel", "reels", "stories", "tv"})


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _normalize_phone_e164(phone: str | None) -> str | None:
    """Parse a raw phone string to Colombian E.164 (+57XXXXXXXXXX).

    Returns ``None`` if the number is absent, unparseable, or invalid.
    """
    if not phone:
        return None
    try:
        parsed = phonenumbers.parse(phone, "CO")
        if phonenumbers.is_valid_number(parsed):
            e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            # Guard: BusinessRaw regex requires +57 + exactly 10 digits
            if e164.startswith("+57") and len(e164) == 13:
                return e164
    except phonenumbers.NumberParseException:
        pass
    return None


def _detect_whatsapp(website: str | None, extra_text: str | None = None) -> bool:
    """Return True if any supplied text contains a WhatsApp indicator."""
    combined = " ".join(t for t in (website, extra_text) if t).lower()
    return any(kw in combined for kw in _WHATSAPP_KEYWORDS)


def _extract_instagram_handle(website: str | None) -> str | None:
    """Extract the Instagram username from a website URL, or return None."""
    if not website:
        return None
    match = _INSTAGRAM_RE.search(website)
    if match:
        handle = match.group(1)
        if handle.lower() not in _IG_RESERVED:
            return handle
    return None


def _extract_category(types: list[str] | None) -> str | None:
    """Build a human-readable category string from Google Places ``types``."""
    if not types:
        return None
    specific = [t.replace("_", " ") for t in types if t not in _GENERIC_TYPES]
    if specific:
        return ", ".join(specific[:3])
    return ", ".join(t.replace("_", " ") for t in types[:2])


# ---------------------------------------------------------------------------
# Public normaliser
# ---------------------------------------------------------------------------


def google_place_to_business_raw(
    place: dict[str, Any],
    details: dict[str, Any],
    city: str,
) -> BusinessRaw:
    """Convert a Google Places API pair into a validated BusinessRaw instance.

    ``place`` is one item from a Nearby Search ``results`` list.
    ``details`` is the Place Details ``result`` for the same place_id.
    Fields missing from the API response become ``None``; BusinessRaw
    validators are the final gate.

    Args:
        place:   Nearby Search result dict.
        details: Place Details result dict (may be empty if the call failed).
        city:    Canonical city name — must be ``"Medellín"`` or ``"Bogotá"``.

    Returns:
        A validated ``BusinessRaw`` instance.

    Raises:
        pydantic.ValidationError: If required fields are absent or invalid.
    """
    # Identity
    place_id: str = details.get("place_id") or place.get("place_id", "")
    if not place_id:
        raise ValueError("place_id is missing — cannot create BusinessRaw without source_id")
    name: str = details.get("name") or place.get("name", "")

    # Location — prefer details (has formatted_address), fall back to place (vicinity)
    geometry = details.get("geometry") or place.get("geometry") or {}
    loc = geometry.get("location") or {}
    lat: float | None = loc.get("lat")
    lng: float | None = loc.get("lng")
    address_raw: str | None = details.get("formatted_address") or place.get("vicinity")

    # Contact
    phone_raw: str | None = details.get("formatted_phone_number") or details.get(
        "international_phone_number"
    )
    phone_e164 = _normalize_phone_e164(phone_raw)

    # Metrics — clamp rating to [0, 5] defensively
    rating_val = details.get("rating") or place.get("rating")
    rating: float | None = None
    if rating_val is not None:
        try:
            rating = max(0.0, min(5.0, float(rating_val)))
        except (TypeError, ValueError):
            logger.warning(f"Ignoring non-numeric rating {rating_val!r} for {place_id}")

    reviews_val = details.get("user_ratings_total") or place.get("user_ratings_total")
    reviews_count: int | None = None
    if reviews_val is not None:
        try:
            reviews_count = int(reviews_val)
        except (TypeError, ValueError):
            pass

    # Classification
    types: list[str] = details.get("types") or place.get("types") or []
    category_raw = _extract_category(types)

    # Online presence
    website: str | None = details.get("website") or None
    whatsapp_flag = _detect_whatsapp(website)
    instagram_handle = _extract_instagram_handle(website)

    return BusinessRaw(
        source=SourceName.GMAPS,
        source_id=place_id,
        name=name,
        city=city,
        address_raw=address_raw,
        lat=lat,
        lng=lng,
        phone_raw=phone_raw,
        phone_e164=phone_e164,
        rating=rating,
        reviews_count=reviews_count,
        category_raw=category_raw,
        website=website,
        whatsapp_flag=whatsapp_flag,
        instagram_handle=instagram_handle,
    )
