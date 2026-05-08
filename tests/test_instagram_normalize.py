"""Unit tests for scrapers.instagram.normalize (no network calls)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from scrapers.instagram.normalize import (
    _detect_catalog,
    _detect_phone,
    _detect_whatsapp,
    profile_to_business_raw,
)

# ---------------------------------------------------------------------------
# _detect_phone
# ---------------------------------------------------------------------------


class TestDetectPhone:
    def test_full_format_with_plus57(self):
        assert _detect_phone("+57 3001234567") == "+57 3001234567"

    def test_bare_10_digit(self):
        assert _detect_phone("Llámanos: 3151234567") == "3151234567"

    def test_57_prefix_no_plus(self):
        assert _detect_phone("57 3009876543") == "57 3009876543"

    def test_no_phone_in_text(self):
        assert _detect_phone("Ropa femenina | Medellín") is None

    def test_empty_string(self):
        assert _detect_phone("") is None

    def test_none_input(self):
        assert _detect_phone(None) is None

    def test_landline_ignored(self):
        # 7-digit landline — should not match (doesn't start with 3)
        assert _detect_phone("Tel: 2345678") is None


# ---------------------------------------------------------------------------
# _detect_whatsapp
# ---------------------------------------------------------------------------


class TestDetectWhatsapp:
    def test_wa_me_link_in_bio(self):
        assert _detect_whatsapp("Escríbenos: wa.me/573001234567", None) is True

    def test_whatsapp_keyword_in_bio(self):
        assert _detect_whatsapp("Pedidos por WhatsApp", None) is True

    def test_api_whatsapp_in_url(self):
        assert _detect_whatsapp(None, "https://api.whatsapp.com/send?phone=57300") is True

    def test_no_signal(self):
        assert _detect_whatsapp("Ropa | Bogotá", "https://mi-tienda.com") is False

    def test_both_none(self):
        assert _detect_whatsapp(None, None) is False

    def test_case_insensitive(self):
        assert _detect_whatsapp("WHATSAPP nos aquí", None) is True


# ---------------------------------------------------------------------------
# _detect_catalog
# ---------------------------------------------------------------------------


class TestDetectCatalog:
    def test_view_shop_in_bio(self):
        assert _detect_catalog("View Shop ↓", None) is True

    def test_tienda_in_bio(self):
        assert _detect_catalog("Visita nuestra tienda", None) is True

    def test_linktree_external(self):
        assert _detect_catalog(None, "https://linktree.me/mitienda") is True

    def test_catalogo_with_accent(self):
        assert _detect_catalog("Nuestro catálogo disponible", None) is True

    def test_no_signal(self):
        assert _detect_catalog("Fotografía | Medellín", None) is False

    def test_both_none(self):
        assert _detect_catalog(None, None) is False


# ---------------------------------------------------------------------------
# profile_to_business_raw — integration-style (mocked instaloader Profile)
# ---------------------------------------------------------------------------


def _make_profile(
    username="matienda",
    full_name="Ma Tienda",
    biography="Ropa | wa.me/573001234567 | 3001234567",
    followers=1500,
    mediacount=80,
    external_url="https://linktree.me/matienda",
    posts=None,
):
    """Build a minimal instaloader Profile mock."""
    profile = MagicMock()
    profile.username = username
    profile.full_name = full_name
    profile.biography = biography
    profile.followers = followers
    profile.mediacount = mediacount
    profile.external_url = external_url

    if posts is None:
        # Default: one recent post
        post = MagicMock()
        post.date_utc = datetime(2026, 4, 1, tzinfo=timezone.utc)
        profile.get_posts.return_value = iter([post])
    else:
        profile.get_posts.return_value = iter(posts)

    return profile


class TestProfileToBusinessRaw:
    def test_basic_fields(self):
        profile = _make_profile()
        biz = profile_to_business_raw(profile, "Medellín")
        assert biz.source == "instagram"
        assert biz.source_id == "matienda"
        assert biz.instagram_handle == "matienda"
        assert biz.city == "Medellín"
        assert biz.instagram_followers == 1500
        assert biz.instagram_posts_count == 80

    def test_whatsapp_detected_from_bio(self):
        profile = _make_profile(biography="Pedidos por WhatsApp 3001234567")
        biz = profile_to_business_raw(profile, "Bogotá")
        assert biz.whatsapp_flag is True

    def test_phone_extracted_from_bio(self):
        profile = _make_profile(biography="Llámanos: 3151234567")
        biz = profile_to_business_raw(profile, "Medellín")
        assert biz.phone_raw == "3151234567"

    def test_catalog_detected(self):
        profile = _make_profile(external_url="https://linktree.me/x")
        biz = profile_to_business_raw(profile, "Medellín")
        assert biz.instagram_has_catalog is True

    def test_no_catalog(self):
        profile = _make_profile(biography="Fotografía artística", external_url=None)
        biz = profile_to_business_raw(profile, "Bogotá")
        assert biz.instagram_has_catalog is False

    def test_invalid_city_raises(self):
        profile = _make_profile()
        with pytest.raises(ValueError):
            profile_to_business_raw(profile, "Cali")

    def test_no_posts_sets_last_post_none(self):
        profile = _make_profile(posts=[])
        biz = profile_to_business_raw(profile, "Medellín")
        assert biz.instagram_last_post_at is None

    def test_inactive_flag_set_for_old_post(self):
        post = MagicMock()
        post.date_utc = datetime(2020, 1, 1, tzinfo=timezone.utc)
        profile = _make_profile(posts=[post])
        biz = profile_to_business_raw(profile, "Medellín")
        assert "inactive_instagram" in biz.quality_flags

    def test_extra_fields_merged(self):
        profile = _make_profile()
        biz = profile_to_business_raw(profile, "Medellín", extra={"category_raw": "clothing store"})
        assert biz.category_raw == "clothing store"

    def test_full_name_fallback_to_username(self):
        profile = _make_profile(full_name="")
        biz = profile_to_business_raw(profile, "Medellín")
        assert biz.name == "matienda"
