"""Unit tests for scrapers.gmaps — no live Google Maps API calls."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from scrapers.gmaps.categories import CATEGORIES, get_keyword
from scrapers.gmaps.cities import CITIES, get_city
from scrapers.gmaps.normalize import (
    _detect_whatsapp,
    _extract_category,
    _extract_instagram_handle,
    _normalize_phone_e164,
    google_place_to_business_raw,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_PLACE: dict = {
    "place_id": "ChIJtest001",
    "name": "Restaurante El Jardín",
    "vicinity": "Cra 45 # 53-24, El Poblado",
    "geometry": {"location": {"lat": 6.2086, "lng": -75.5672}},
    "rating": 4.3,
    "user_ratings_total": 127,
    "types": ["restaurant", "food", "point_of_interest", "establishment"],
}

_DETAILS: dict = {
    "place_id": "ChIJtest001",
    "name": "Restaurante El Jardín",
    "formatted_address": "Cra 45 # 53-24, El Poblado, Medellín, Antioquia, Colombia",
    "geometry": {"location": {"lat": 6.2086, "lng": -75.5672}},
    "formatted_phone_number": "300 123 4567",
    "rating": 4.3,
    "user_ratings_total": 127,
    "types": ["restaurant", "food", "point_of_interest", "establishment"],
    "website": "https://restaurante-eljardin.co",
}

# ---------------------------------------------------------------------------
# City slug mapping
# ---------------------------------------------------------------------------


def test_medellin_slug_returns_canonical_name():
    assert get_city("medellin").canonical_name == "Medellín"


def test_bogota_slug_returns_canonical_name():
    assert get_city("bogota").canonical_name == "Bogotá"


def test_medellin_has_valid_coordinates():
    cfg = get_city("medellin")
    assert 5.0 < cfg.center_lat < 8.0
    assert -77.0 < cfg.center_lng < -74.0


def test_bogota_has_valid_coordinates():
    cfg = get_city("bogota")
    assert 3.0 < cfg.center_lat < 6.0
    assert -76.0 < cfg.center_lng < -72.0


def test_all_city_slugs_present():
    for slug in ("medellin", "bogota"):
        assert slug in CITIES


def test_invalid_city_slug_raises_key_error():
    with pytest.raises(KeyError, match="cali"):
        get_city("cali")


# ---------------------------------------------------------------------------
# Category lookup
# ---------------------------------------------------------------------------


def test_restaurants_returns_spanish_keyword():
    assert "restaurante" in get_keyword("restaurants").lower()


def test_beauty_salons_returns_spanish_keyword():
    kw = get_keyword("beauty_salons")
    assert "sal" in kw.lower()  # "salón de belleza"


def test_all_category_slugs_resolve_to_nonempty_string():
    for slug in CATEGORIES:
        kw = get_keyword(slug)
        assert isinstance(kw, str) and kw.strip()


def test_invalid_category_raises_key_error():
    with pytest.raises(KeyError, match="nonexistent"):
        get_keyword("nonexistent")


# ---------------------------------------------------------------------------
# Phone normalisation
# ---------------------------------------------------------------------------


def test_mobile_with_country_code_normalises():
    assert _normalize_phone_e164("+57 300 123 4567") == "+573001234567"


def test_mobile_without_country_code_normalises():
    assert _normalize_phone_e164("300 123 4567") == "+573001234567"


def test_medellin_landline_normalises():
    # Medellín landline: 604 + 7 digits = 10 digits total
    result = _normalize_phone_e164("604 311 2200")
    assert result is not None
    assert result.startswith("+57")
    assert len(result) == 13


def test_none_phone_returns_none():
    assert _normalize_phone_e164(None) is None


def test_empty_string_returns_none():
    assert _normalize_phone_e164("") is None


def test_garbage_string_returns_none():
    assert _normalize_phone_e164("not-a-phone-number") is None


def test_too_short_number_returns_none():
    assert _normalize_phone_e164("123") is None


# ---------------------------------------------------------------------------
# WhatsApp detection
# ---------------------------------------------------------------------------


def test_wa_me_link_detected():
    assert _detect_whatsapp("https://wa.me/573001234567") is True


def test_api_whatsapp_link_detected():
    assert _detect_whatsapp("https://api.whatsapp.com/send?phone=573001234567") is True


def test_whatsapp_word_in_url_detected():
    assert _detect_whatsapp("https://chat.whatsapp.com/abc123") is True


def test_regular_website_not_flagged():
    assert _detect_whatsapp("https://example.com") is False


def test_none_website_returns_false():
    assert _detect_whatsapp(None) is False


def test_extra_text_also_checked():
    assert _detect_whatsapp(None, extra_text="contacta por wa.me") is True


# ---------------------------------------------------------------------------
# Instagram handle extraction
# ---------------------------------------------------------------------------


def test_handle_extracted_from_full_url():
    assert _extract_instagram_handle("https://www.instagram.com/mi_negocio/") == "mi_negocio"


def test_handle_extracted_without_trailing_slash():
    assert _extract_instagram_handle("https://instagram.com/tienda_co") == "tienda_co"


def test_handle_with_dots_and_numbers():
    assert _extract_instagram_handle("https://instagram.com/tienda.co2024") == "tienda.co2024"


def test_non_instagram_url_returns_none():
    assert _extract_instagram_handle("https://facebook.com/page") is None


def test_none_url_returns_none():
    assert _extract_instagram_handle(None) is None


def test_reserved_path_p_returns_none():
    # instagram.com/p/... is a post permalink, not a handle
    assert _extract_instagram_handle("https://www.instagram.com/p/CxYZ123/") is None


# ---------------------------------------------------------------------------
# Category extraction
# ---------------------------------------------------------------------------


def test_generic_types_filtered_out():
    result = _extract_category(["restaurant", "food", "point_of_interest", "establishment"])
    assert result == "restaurant"


def test_underscores_replaced_with_spaces():
    result = _extract_category(["beauty_salon", "health", "establishment"])
    assert result == "beauty salon"


def test_empty_types_returns_none():
    assert _extract_category([]) is None


def test_none_types_returns_none():
    assert _extract_category(None) is None


def test_all_generic_falls_back_to_first_two():
    result = _extract_category(["point_of_interest", "establishment"])
    assert result is not None and len(result) > 0


# ---------------------------------------------------------------------------
# Full normalisation — google_place_to_business_raw
# ---------------------------------------------------------------------------


def test_valid_place_produces_correct_business_raw():
    biz = google_place_to_business_raw(_PLACE, _DETAILS, "Medellín")
    assert biz.source == "gmaps"
    assert biz.source_id == "ChIJtest001"
    assert biz.name == "Restaurante El Jardín"
    assert biz.city == "Medellín"
    assert biz.lat == pytest.approx(6.2086)
    assert biz.lng == pytest.approx(-75.5672)
    assert biz.rating == pytest.approx(4.3)
    assert biz.reviews_count == 127
    assert biz.phone_e164 == "+573001234567"
    assert biz.whatsapp_flag is False
    assert biz.address_raw is not None


def test_minimal_place_with_empty_details_does_not_crash():
    """Only place_id and name are required; all other fields may be absent."""
    biz = google_place_to_business_raw(
        {"place_id": "ChIJminimal", "name": "Negocio Mínimo"},
        {},
        "Bogotá",
    )
    assert biz.source_id == "ChIJminimal"
    assert biz.city == "Bogotá"
    assert biz.lat is None
    assert biz.lng is None
    assert biz.phone_e164 is None
    assert biz.whatsapp_flag is False


def test_whatsapp_website_sets_flag():
    details_wa = {**_DETAILS, "website": "https://wa.me/573001234567"}
    biz = google_place_to_business_raw(_PLACE, details_wa, "Medellín")
    assert biz.whatsapp_flag is True


def test_instagram_website_extracts_handle():
    details_ig = {**_DETAILS, "website": "https://www.instagram.com/rest_jardin/"}
    biz = google_place_to_business_raw(_PLACE, details_ig, "Medellín")
    assert biz.instagram_handle == "rest_jardin"


def test_details_address_preferred_over_place_vicinity():
    biz = google_place_to_business_raw(_PLACE, _DETAILS, "Medellín")
    # formatted_address from details is more complete than vicinity from place
    assert "Colombia" in (biz.address_raw or "")


def test_invalid_city_raises_validation_error():
    with pytest.raises(ValidationError):
        google_place_to_business_raw(_PLACE, _DETAILS, "Cali")


def test_missing_place_id_raises_value_error():
    """Normaliser rejects a place dict with no place_id before hitting Pydantic."""
    with pytest.raises(ValueError, match="place_id"):
        google_place_to_business_raw({"name": "No ID"}, {}, "Medellín")


def test_quality_flags_added_for_missing_phone():
    """Normaliser returns None phone → BusinessRaw auto-adds missing_phone flag."""
    place_no_phone = {**_PLACE}
    details_no_phone = {k: v for k, v in _DETAILS.items() if "phone" not in k}
    biz = google_place_to_business_raw(place_no_phone, details_no_phone, "Medellín")
    assert "missing_phone" in biz.quality_flags
