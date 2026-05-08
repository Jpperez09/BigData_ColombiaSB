"""Unit tests for the entity resolution pipeline.

All tests are offline — operate on synthetic in-memory DataFrames.
"""

from __future__ import annotations

import polars as pl
import pytest

from scoring.entity_resolution import (
    _first_significant_token,
    _normalise,
    _resolve,
)


# ---------------------------------------------------------------------------
# Name normalisation
# ---------------------------------------------------------------------------


def test_normalise_strips_accents():
    assert _normalise("Café Mañana") == "cafe manana"


def test_normalise_lowercases():
    assert _normalise("RESTAURANTE EL POBLADO") == "restaurante el poblado"


def test_normalise_strips_legal_suffixes():
    assert _normalise("Cooltura Pop S.A.S.") == "cooltura pop"
    assert _normalise("Distribuidora ABC Ltda.") == "distribuidora abc"
    assert _normalise("Grupo XYZ E.U.") == "grupo xyz"


def test_normalise_collapses_whitespace():
    assert _normalise("El   Restaurante  ") == "el restaurante"


# ---------------------------------------------------------------------------
# First significant token
# ---------------------------------------------------------------------------


def test_first_significant_token_skips_restaurante():
    """The bug we're locking in: 'restaurante' must not be a blocking key."""
    assert _first_significant_token("restaurante el poblado") == "poblado"


def test_first_significant_token_skips_articles():
    assert _first_significant_token("el granjero ciudad rio") == "granjero"


def test_first_significant_token_skips_short_words():
    """Tokens under 3 chars are skipped (e.g. 'la')."""
    assert _first_significant_token("la fogata al carbon") == "fogata"


def test_first_significant_token_returns_unique_word():
    """Two different restaurants must get different blocking tokens."""
    a = _first_significant_token(_normalise("Restaurante Jua Jua"))
    b = _first_significant_token(_normalise("Restaurante La Yezka"))
    assert a != b
    assert a == "jua"
    assert b == "yezka"


# ---------------------------------------------------------------------------
# Resolution end-to-end (synthetic data)
# ---------------------------------------------------------------------------


def _make_df(rows: list[dict]) -> pl.DataFrame:
    """Build a DataFrame with all columns needed by _resolve()."""
    base = {
        "name": "",
        "city": "Medellín",
        "phone_e164": None,
        "name_normalised": "",
        "name_first_sig_token": "",
    }
    return pl.DataFrame([{**base, **r} for r in rows])


def test_phone_blocking_merges_same_phone():
    """Two rows with identical (city, phone) must collapse to one master_id."""
    df = _make_df([
        {
            "name": "Pizzeria El Centro",
            "phone_e164": "+573001234567",
            "name_normalised": "pizzeria el centro",
            "name_first_sig_token": "pizzeria",
        },
        {
            "name": "Pizzería Centro",
            "phone_e164": "+573001234567",
            "name_normalised": "pizzeria centro",
            "name_first_sig_token": "pizzeria",
        },
    ])
    out = _resolve(df, threshold=85)
    assert out["master_id"].n_unique() == 1


def test_different_restaurants_keep_distinct_master_ids():
    """The exact regression: 'Restaurante X' and 'Restaurante Y' must not merge."""
    df = _make_df([
        {
            "name": "Restaurante Jua Jua",
            "name_normalised": "restaurante jua jua",
            "name_first_sig_token": "jua",
        },
        {
            "name": "Restaurante La Yezka",
            "name_normalised": "restaurante la yezka",
            "name_first_sig_token": "yezka",
        },
        {
            "name": "Restaurante El Patio",
            "name_normalised": "restaurante el patio",
            "name_first_sig_token": "patio",
        },
    ])
    out = _resolve(df, threshold=85)
    assert out["master_id"].n_unique() == 3


def test_fuzzy_match_within_block_merges_close_names():
    """Same significant token + close fuzzy match → merge."""
    df = _make_df([
        {
            "name": "Panaderia La Espiga",
            "name_normalised": "panaderia la espiga",
            "name_first_sig_token": "espiga",
        },
        {
            "name": "Panaderia La Espiga Dorada",
            "name_normalised": "panaderia la espiga dorada",
            "name_first_sig_token": "espiga",
        },
    ])
    out = _resolve(df, threshold=85)
    assert out["master_id"].n_unique() == 1


def test_different_cities_never_merge():
    """Same name, different city = different entities."""
    df = _make_df([
        {
            "name": "Cafeteria Central",
            "city": "Medellín",
            "name_normalised": "cafeteria central",
            "name_first_sig_token": "central",
        },
        {
            "name": "Cafeteria Central",
            "city": "Bogotá",
            "name_normalised": "cafeteria central",
            "name_first_sig_token": "central",
        },
    ])
    out = _resolve(df, threshold=85)
    assert out["master_id"].n_unique() == 2


def test_master_id_is_deterministic():
    """Same input → same master_id across runs (stable UUID5)."""
    df = _make_df([
        {
            "name": "Mi Tienda",
            "name_normalised": "mi tienda",
            "name_first_sig_token": "tienda",
        },
    ])
    a = _resolve(df, threshold=85)["master_id"][0]
    b = _resolve(df, threshold=85)["master_id"][0]
    assert a == b


def test_phone_blocking_overrides_name_block():
    """If two rows share a phone but have very different names → still merge."""
    df = _make_df([
        {
            "name": "Veterinaria Animales Felices",
            "phone_e164": "+573159998877",
            "name_normalised": "veterinaria animales felices",
            "name_first_sig_token": "animales",
        },
        {
            "name": "Centro Veterinario Animales Felices",
            "phone_e164": "+573159998877",
            "name_normalised": "centro veterinario animales felices",
            "name_first_sig_token": "veterinario",
        },
    ])
    out = _resolve(df, threshold=85)
    assert out["master_id"].n_unique() == 1
