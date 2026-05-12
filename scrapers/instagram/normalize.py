"""Convert an instaloader Profile into a validated BusinessRaw instance."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from loguru import logger

from utils.models import BusinessRaw, QualityFlag, SourceName

if TYPE_CHECKING:
    import instaloader

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Colombian phone: +57, 57, or bare 10-digit cell starting with 3
_CO_PHONE_RE = re.compile(r"(?:(?:\+?57)[\s\-]?)?(?<!\d)(3\d{9})(?!\d)")

_WHATSAPP_RE = re.compile(r"(wa\.me|api\.whatsapp\.com|whatsapp)", re.IGNORECASE)

# Bio / external_url signals for an active product catalogue
_CATALOG_SIGNALS = re.compile(
    r"(view shop|tienda|cat[aá]logo|shop now|link\.bio|linktree|bio\.site|instashop)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _detect_phone(text: str | None) -> str | None:
    """Return the first Colombian mobile number found in text, raw format."""
    if not text:
        return None
    match = _CO_PHONE_RE.search(text)
    return match.group(0).strip() if match else None


def _detect_whatsapp(bio: str | None, external_url: str | None) -> bool:
    """Return True if bio or external_url contains a WhatsApp indicator."""
    for t in (bio, external_url):
        if t and _WHATSAPP_RE.search(t):
            return True
    return False


def _detect_catalog(bio: str | None, external_url: str | None) -> bool:
    """Return True if the profile appears to have an active product catalogue."""
    for t in (bio, external_url):
        if t and _CATALOG_SIGNALS.search(t):
            return True
    return False


def _last_post_date(profile: instaloader.Profile) -> datetime | None:
    """Return the UTC datetime of the most recent post, or None."""
    try:
        post = next(iter(profile.get_posts()))
        dt = post.date_utc
        # Ensure timezone-aware so comparison with datetime.now(timezone.utc) works
        if dt is not None and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except StopIteration:
        return None
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"Could not fetch last post for @{profile.username}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Public normaliser
# ---------------------------------------------------------------------------


def profile_to_business_raw(
    profile: instaloader.Profile,
    city: str,
    extra: dict[str, Any] | None = None,
) -> BusinessRaw:
    """Convert an instaloader Profile to a validated BusinessRaw instance.

    Args:
        profile: An instaloader Profile object (fetched in no-login mode).
        city:    Canonical city name — inherited from the gmaps seed row.
                 Must be ``"Medellín"`` or ``"Bogotá"``.
        extra:   Optional dict of extra fields to merge (e.g. category_raw
                 from the gmaps seed row).

    Returns:
        A validated ``BusinessRaw`` instance.

    Raises:
        pydantic.ValidationError: If required fields fail validation.
    """
    bio: str | None = profile.biography or None
    external_url: str | None = profile.external_url or None

    phone_raw = _detect_phone(bio)
    whatsapp_flag = _detect_whatsapp(bio, external_url) or (phone_raw is not None)
    has_catalog = _detect_catalog(bio, external_url)
    last_post = _last_post_date(profile)

    flags: list[str] = []
    if last_post is not None:
        days_since = (datetime.now(timezone.utc) - last_post).days
        if days_since > 180:
            flags.append(QualityFlag.INACTIVE_INSTAGRAM.value)

    return BusinessRaw(
        source=SourceName.INSTAGRAM,
        source_id=profile.username,
        name=profile.full_name or profile.username,
        city=city,
        phone_raw=phone_raw,
        whatsapp_flag=whatsapp_flag,
        instagram_handle=profile.username,
        instagram_followers=profile.followers,
        instagram_posts_count=profile.mediacount,
        instagram_last_post_at=last_post,
        instagram_has_catalog=has_catalog,
        bio_text=bio,
        website=external_url,
        quality_flags=flags,
        **(extra or {}),
    )
