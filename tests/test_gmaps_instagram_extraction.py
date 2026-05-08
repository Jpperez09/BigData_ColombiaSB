"""Unit tests for the Instagram-handle extractor and the websites handoff
parquet generator. All tests are offline (no network, no scraping)."""

from __future__ import annotations

from scrapers.gmaps.run import extract_instagram_handle

# ---------------------------------------------------------------------------
# extract_instagram_handle
# ---------------------------------------------------------------------------


def test_extract_https_www():
    assert extract_instagram_handle("https://www.instagram.com/losportenosmedellin") == (
        "losportenosmedellin"
    )


def test_extract_https_no_www():
    assert extract_instagram_handle("https://instagram.com/panmartipan") == "panmartipan"


def test_extract_http_with_trailing_slash():
    assert extract_instagram_handle("http://instagram.com/some_user/") == "some_user"


def test_extract_with_query_string():
    assert extract_instagram_handle("https://www.instagram.com/cafeteria_x/?hl=es") == (
        "cafeteria_x"
    )


def test_extract_no_scheme():
    assert extract_instagram_handle("instagram.com/example") == "example"


def test_extract_short_url():
    assert extract_instagram_handle("https://instagr.am/short.handle") == "short.handle"


def test_extract_handle_lowercased():
    """Instagram usernames are case-insensitive; we normalise to lowercase."""
    assert extract_instagram_handle("https://www.instagram.com/MyBakery") == "mybakery"


def test_extract_handle_with_period_underscore():
    assert extract_instagram_handle("https://instagram.com/cafe_pasaje.medellin") == (
        "cafe_pasaje.medellin"
    )


# ---------------------------------------------------------------------------
# Reserved paths must NOT be returned as handles
# ---------------------------------------------------------------------------


def test_extract_reject_post_url():
    assert extract_instagram_handle("https://instagram.com/p/Cabc123") is None


def test_extract_reject_reel_url():
    assert extract_instagram_handle("https://instagram.com/reel/xyz") is None


def test_extract_reject_explore():
    assert extract_instagram_handle("https://instagram.com/explore/tags/colombia") is None


def test_extract_reject_accounts():
    assert extract_instagram_handle("https://instagram.com/accounts/login") is None


def test_extract_reject_about():
    assert extract_instagram_handle("https://instagram.com/about/us") is None


# ---------------------------------------------------------------------------
# Non-Instagram URLs return None
# ---------------------------------------------------------------------------


def test_extract_non_instagram_url():
    assert extract_instagram_handle("https://www.example.com/profile") is None


def test_extract_facebook_url():
    assert extract_instagram_handle("https://facebook.com/somepage") is None


def test_extract_empty_or_none():
    assert extract_instagram_handle(None) is None
    assert extract_instagram_handle("") is None


def test_extract_garbage_string():
    assert extract_instagram_handle("not a url at all") is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_extract_uppercase_domain_still_works():
    assert extract_instagram_handle("https://Instagram.Com/myhandle") == "myhandle"


def test_extract_handle_with_invalid_chars_rejected():
    """Username with chars outside [a-z0-9._] (e.g., hyphen, space) → None."""
    # Hyphen is not allowed in IG usernames
    assert extract_instagram_handle("https://instagram.com/has-hyphen") is None


def test_extract_overly_long_handle_rejected():
    """Instagram caps usernames at 30 chars."""
    long = "a" * 31
    assert extract_instagram_handle(f"https://instagram.com/{long}") is None


def test_extract_strips_trailing_slash():
    assert extract_instagram_handle("https://instagram.com/handle/") == "handle"
