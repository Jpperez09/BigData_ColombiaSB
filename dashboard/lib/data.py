"""Cached data loaders for the Streamlit dashboard.

Reads scored businesses from Supabase when credentials are available,
otherwise falls back to ``data/clean/scored.parquet``. Both paths return
identical pandas DataFrames so the rest of the dashboard doesn't care.

Cache TTL is 1 hour per the working plan §8.1.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Paths and config
# ---------------------------------------------------------------------------

_SCORED_PATH = Path("data/clean/scored.parquet")
_DEMO_PATH = Path("data/demo/sample_500.parquet")
_CANONICAL_TABLE = "businesses_canonical"
_CACHE_TTL_SECONDS = 3600  # 1 hour

_VALID_CITIES = ["Medellín", "Bogotá"]


# ---------------------------------------------------------------------------
# Supabase client (lazy)
# ---------------------------------------------------------------------------


def _get_supabase_client() -> Any | None:
    """Return a Supabase client if credentials exist, else None.

    Reads from Streamlit secrets first (Streamlit Cloud deployment), then
    falls back to env vars (local dev with .env loaded).
    """
    url = None
    key = None

    # Streamlit Cloud uses st.secrets — check before env vars
    try:
        url = st.secrets.get("SUPABASE_URL")
        key = st.secrets.get("SUPABASE_SERVICE_KEY") or st.secrets.get("SUPABASE_ANON_KEY")
    except (FileNotFoundError, KeyError):
        pass

    # Local dev: read .env via python-dotenv if present, then os.environ
    if not url or not key:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        url = url or os.environ.get("SUPABASE_URL")
        key = key or os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_ANON_KEY")

    if not url or not key:
        return None

    try:
        from supabase import create_client

        return create_client(url, key)
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------


@st.cache_data(ttl=_CACHE_TTL_SECONDS, show_spinner="Loading businesses…")
def load_businesses() -> pd.DataFrame:
    """Return the scored canonical businesses DataFrame.

    Source priority:
      1. ``data/clean/scored.parquet`` if it exists (has ai_readiness_score
         + per-feature breakdown columns from the scoring pipeline).
      2. Supabase ``businesses_canonical`` (no scores yet — score will be 0).
      3. Empty DataFrame with the expected columns.
    """
    if _SCORED_PATH.exists():
        df = pd.read_parquet(_SCORED_PATH)
        df = _normalise_columns(df)
        return df

    if _DEMO_PATH.exists():
        df = pd.read_parquet(_DEMO_PATH)
        df = _normalise_columns(df)
        return df

    client = _get_supabase_client()
    if client is not None:
        try:
            res = client.table(_CANONICAL_TABLE).select("*").execute()
            df = pd.DataFrame(res.data or [])
            if not df.empty:
                df = _normalise_columns(df)
                if "ai_readiness_score" not in df.columns:
                    df["ai_readiness_score"] = 0.0
                return df
        except Exception:  # noqa: BLE001
            pass

    # Last-resort empty frame with the expected schema
    return pd.DataFrame(
        columns=[
            "name",
            "city",
            "category_raw",
            "neighborhood",
            "phone_e164",
            "website",
            "instagram_handle",
            "rating",
            "reviews_count",
            "lat",
            "lng",
            "ai_readiness_score",
        ]
    )


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure the columns the UI expects exist (fill missing with NA)."""
    expected = [
        "name",
        "city",
        "category_raw",
        "category_slug_enriched",
        "neighborhood",
        "neighborhood_enriched",
        "phone_e164",
        "phone_raw",
        "website",
        "instagram_handle",
        "instagram_followers",
        "instagram_has_catalog",
        "rating",
        "reviews_count",
        "lat",
        "lng",
        "ai_readiness_score",
        "whatsapp_flag",
    ]
    for col in expected:
        if col not in df.columns:
            df[col] = pd.NA
    # Prefer enriched columns when present
    if "category_slug_enriched" in df.columns:
        df["category_display"] = df["category_slug_enriched"].fillna(df["category_raw"])
    else:
        df["category_display"] = df["category_raw"]
    if "neighborhood_enriched" in df.columns:
        df["neighborhood_display"] = df["neighborhood_enriched"].fillna(df["neighborhood"])
    else:
        df["neighborhood_display"] = df["neighborhood"]
    return df


@st.cache_data(ttl=_CACHE_TTL_SECONDS)
def get_unique_categories(df: pd.DataFrame) -> list[str]:
    if df.empty or "category_display" not in df.columns:
        return []
    return sorted(c for c in df["category_display"].dropna().unique() if c)


@st.cache_data(ttl=_CACHE_TTL_SECONDS)
def get_unique_neighborhoods(df: pd.DataFrame) -> list[str]:
    if df.empty or "neighborhood_display" not in df.columns:
        return []
    return sorted(n for n in df["neighborhood_display"].dropna().unique() if n)


def get_data_source_label() -> str:
    """Human-readable label of where the current data came from."""
    if _SCORED_PATH.exists():
        return f"local parquet ({_SCORED_PATH})"
    if _DEMO_PATH.exists():
        return "demo dataset — 500 sampled businesses (data/demo/sample_500.parquet)"
    if _get_supabase_client() is not None:
        return "Supabase (no scores)"
    return "no data source available"
