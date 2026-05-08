"""Unit tests for scoring/features.py — every feature function in isolation,
plus a smoke test of the weighted-sum integration.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scoring.features import (
    catalog_signal,
    geographic_weight,
    instagram_activity,
    instagram_reach,
    review_volume,
    score_row,
    vertical_weight,
    whatsapp_signal,
)

# ---------------------------------------------------------------------------
# whatsapp_signal
# ---------------------------------------------------------------------------


def test_whatsapp_signal_full_when_flagged():
    assert whatsapp_signal(True, "+573001234567") == 1.0


def test_whatsapp_signal_half_when_phone_only():
    assert whatsapp_signal(False, "+573001234567") == 0.5


def test_whatsapp_signal_zero_when_no_phone():
    assert whatsapp_signal(False, None) == 0.0
    assert whatsapp_signal(None, None) == 0.0


def test_whatsapp_signal_flag_overrides_missing_phone():
    """If the source explicitly says WhatsApp but didn't keep the phone, still 1.0."""
    assert whatsapp_signal(True, None) == 1.0


# ---------------------------------------------------------------------------
# instagram_reach
# ---------------------------------------------------------------------------


def test_instagram_reach_zero_when_none():
    assert instagram_reach(None) == 0.0
    assert instagram_reach(0) == 0.0


def test_instagram_reach_increases_monotonically():
    assert instagram_reach(100) < instagram_reach(1_000) < instagram_reach(10_000)


def test_instagram_reach_capped_at_one():
    assert instagram_reach(1_000_000) == 1.0
    assert instagram_reach(50_000) == pytest.approx(1.0, abs=0.01)


def test_instagram_reach_in_unit_interval():
    for n in (1, 10, 500, 5_000, 100_000):
        v = instagram_reach(n)
        assert 0.0 <= v <= 1.0


# ---------------------------------------------------------------------------
# instagram_activity
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)


def test_instagram_activity_full_within_seven_days():
    assert instagram_activity(_now() - timedelta(days=2), now=_now()) == 1.0
    assert instagram_activity(_now() - timedelta(days=7), now=_now()) == 1.0


def test_instagram_activity_zero_after_180_days():
    assert instagram_activity(_now() - timedelta(days=180), now=_now()) == 0.0
    assert instagram_activity(_now() - timedelta(days=365), now=_now()) == 0.0


def test_instagram_activity_decays_in_between():
    a = instagram_activity(_now() - timedelta(days=30), now=_now())
    b = instagram_activity(_now() - timedelta(days=90), now=_now())
    c = instagram_activity(_now() - timedelta(days=150), now=_now())
    assert 0 < c < b < a < 1


def test_instagram_activity_none_returns_zero():
    assert instagram_activity(None, now=_now()) == 0.0


def test_instagram_activity_naive_datetime_treated_as_utc():
    naive = (_now() - timedelta(days=2)).replace(tzinfo=None)
    assert instagram_activity(naive, now=_now()) == 1.0


# ---------------------------------------------------------------------------
# catalog_signal
# ---------------------------------------------------------------------------


def test_catalog_signal_true():
    assert catalog_signal(True) == 1.0


def test_catalog_signal_false_or_none():
    assert catalog_signal(False) == 0.0
    assert catalog_signal(None) == 0.0


# ---------------------------------------------------------------------------
# review_volume
# ---------------------------------------------------------------------------


def test_review_volume_zero_when_none_or_zero():
    assert review_volume(None) == 0.0
    assert review_volume(0) == 0.0


def test_review_volume_increases_monotonically():
    assert review_volume(5) < review_volume(50) < review_volume(500)


def test_review_volume_capped_at_one():
    assert review_volume(10_000) == 1.0


# ---------------------------------------------------------------------------
# vertical_weight
# ---------------------------------------------------------------------------


def test_vertical_weight_known_category():
    table = {"verticals": {"restaurants": 1.0, "auto_repair": 0.5}, "default": 0.7}
    assert vertical_weight("restaurants", table) == 1.0
    assert vertical_weight("auto_repair", table) == 0.5


def test_vertical_weight_unknown_falls_back_to_default():
    table = {"verticals": {"restaurants": 1.0}, "default": 0.7}
    assert vertical_weight("space_lasers", table) == 0.7
    assert vertical_weight(None, table) == 0.7


# ---------------------------------------------------------------------------
# geographic_weight
# ---------------------------------------------------------------------------


def test_geographic_weight_known_neighborhood():
    table = {
        "cities": {
            "medellin": {"el_poblado_provenza_lleras": 1.0, "belen_rosales": 0.8},
        },
        "city_default": 0.8,
        "default": 0.6,
    }
    assert geographic_weight("medellin", "el_poblado_provenza_lleras", table) == 1.0
    assert geographic_weight("medellin", "belen_rosales", table) == 0.8


def test_geographic_weight_unknown_neighborhood_uses_city_default():
    table = {
        "cities": {"medellin": {"el_poblado_provenza_lleras": 1.0}},
        "city_default": 0.8,
        "default": 0.6,
    }
    assert geographic_weight("medellin", "moravia", table) == 0.8


def test_geographic_weight_unknown_city_uses_default():
    table = {
        "cities": {"medellin": {}},
        "city_default": 0.8,
        "default": 0.6,
    }
    assert geographic_weight("cali", "centro", table) == 0.6
    assert geographic_weight(None, None, table) == 0.6


# ---------------------------------------------------------------------------
# score_row — integration smoke test
# ---------------------------------------------------------------------------


def test_score_row_perfect_business_hits_100():
    weights = {
        "whatsapp_signal": 0.20,
        "instagram_reach": 0.15,
        "instagram_activity": 0.15,
        "catalog_signal": 0.10,
        "review_volume": 0.10,
        "vertical_weight": 0.20,
        "geographic_weight": 0.10,
    }
    vertical_table = {"verticals": {"restaurants": 1.0}, "default": 0.7}
    geo_table = {
        "cities": {"medellin": {"el_poblado_provenza_lleras": 1.0}},
        "city_default": 0.8,
        "default": 0.6,
    }
    row = {
        "whatsapp_flag": True,
        "phone_e164": "+573001234567",
        "instagram_followers": 100_000,  # caps to 1.0
        "instagram_last_post_at": _now(),
        "instagram_has_catalog": True,
        "reviews_count": 5_000,  # caps to 1.0
        "category_raw": "restaurants",
        "city": "Medellín",
        "neighborhood": "el_poblado_provenza_lleras",
    }
    score, _ = score_row(
        row,
        weights=weights,
        vertical_table=vertical_table,
        geographic_table=geo_table,
        now=_now(),
    )
    assert score == pytest.approx(100.0, abs=0.5)


def test_score_row_zero_business_hits_zero():
    weights = {
        "whatsapp_signal": 0.20,
        "instagram_reach": 0.15,
        "instagram_activity": 0.15,
        "catalog_signal": 0.10,
        "review_volume": 0.10,
        "vertical_weight": 0.20,
        "geographic_weight": 0.10,
    }
    vertical_table = {"verticals": {}, "default": 0.0}
    geo_table = {"cities": {}, "city_default": 0.0, "default": 0.0}
    row = {
        "whatsapp_flag": False,
        "phone_e164": None,
        "instagram_followers": None,
        "instagram_last_post_at": None,
        "instagram_has_catalog": False,
        "reviews_count": None,
        "category_raw": "unknown",
        "city": None,
        "neighborhood": None,
    }
    score, _ = score_row(
        row,
        weights=weights,
        vertical_table=vertical_table,
        geographic_table=geo_table,
        now=_now(),
    )
    assert score == 0.0


def test_score_row_returns_features_in_unit_interval():
    weights = {
        "whatsapp_signal": 1.0,
        "instagram_reach": 1.0,
        "instagram_activity": 1.0,
        "catalog_signal": 1.0,
        "review_volume": 1.0,
        "vertical_weight": 1.0,
        "geographic_weight": 1.0,
    }
    vertical_table = {"verticals": {"restaurants": 1.0}, "default": 0.7}
    geo_table = {
        "cities": {"medellin": {"el_poblado_provenza_lleras": 1.0}},
        "city_default": 0.8,
        "default": 0.6,
    }
    row = {
        "whatsapp_flag": False,
        "phone_e164": "+573001234567",
        "instagram_followers": 250,
        "instagram_last_post_at": _now() - timedelta(days=45),
        "instagram_has_catalog": False,
        "reviews_count": 80,
        "category_raw": "restaurants",
        "city": "Medellín",
        "neighborhood": "el_poblado_provenza_lleras",
    }
    _, feats = score_row(
        row,
        weights=weights,
        vertical_table=vertical_table,
        geographic_table=geo_table,
        now=_now(),
    )
    for k, v in feats.items():
        assert 0.0 <= v <= 1.0, f"{k} out of range: {v}"
