"""Shared filter widgets for the dashboard sidebar.

All pages render the same filter block in the sidebar so navigating between
pages preserves the user's mental context. The filters are stored in
``st.session_state`` under stable keys so a selection on one page sticks
when you switch to another.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.lib.data import get_unique_categories, get_unique_neighborhoods


def render_sidebar_filters(df: pd.DataFrame) -> dict:
    """Render the filter sidebar; return a dict of selected values.

    Keys: cities, categories, score_range, has_whatsapp, has_instagram,
    neighborhoods, search.
    """
    st.sidebar.markdown("### Filters")

    # City multiselect (defaults to all)
    available_cities = sorted(df["city"].dropna().unique()) if not df.empty else []
    cities = st.sidebar.multiselect(
        "City",
        options=available_cities,
        default=available_cities,
        key="filter_cities",
    )

    # Category multiselect
    available_cats = get_unique_categories(df)
    categories = st.sidebar.multiselect(
        "Vertical",
        options=available_cats,
        default=[],
        key="filter_categories",
        help="Empty = all verticals",
    )

    # Score range slider
    if not df.empty and df["ai_readiness_score"].notna().any():
        score_min = float(df["ai_readiness_score"].min())
        score_max = float(df["ai_readiness_score"].max())
    else:
        score_min, score_max = 0.0, 100.0
    # Ensure min < max even if all rows have the same score
    if score_min == score_max:
        score_max = score_min + 1.0
    score_range = st.sidebar.slider(
        "AI Readiness score",
        min_value=0.0,
        max_value=100.0,
        value=(round(score_min, 1), round(score_max, 1)),
        step=1.0,
        key="filter_score_range",
    )

    # Boolean filters
    st.sidebar.markdown("**Channel signals**")
    has_whatsapp = st.sidebar.checkbox(
        "Has WhatsApp / phone",
        value=False,
        key="filter_has_whatsapp",
    )
    has_instagram = st.sidebar.checkbox(
        "Has Instagram",
        value=False,
        key="filter_has_instagram",
    )
    has_website = st.sidebar.checkbox(
        "Has website",
        value=False,
        key="filter_has_website",
    )

    # Neighborhood (collapsible since it's long)
    with st.sidebar.expander("Neighborhood", expanded=False):
        available_zones = get_unique_neighborhoods(df)
        neighborhoods = st.multiselect(
            "Zones",
            options=available_zones,
            default=[],
            key="filter_neighborhoods",
            help="Empty = all zones",
            label_visibility="collapsed",
        )

    # Free-text search
    search = st.sidebar.text_input(
        "Search by name",
        value="",
        key="filter_search",
        placeholder="e.g. panaderia",
    )

    return {
        "cities": cities,
        "categories": categories,
        "score_range": score_range,
        "has_whatsapp": has_whatsapp,
        "has_instagram": has_instagram,
        "has_website": has_website,
        "neighborhoods": neighborhoods,
        "search": search,
    }


def apply_filters(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    """Apply the filter dict from ``render_sidebar_filters`` to a DataFrame."""
    if df.empty:
        return df

    out = df.copy()

    if f["cities"]:
        out = out[out["city"].isin(f["cities"])]

    if f["categories"]:
        out = out[out["category_display"].isin(f["categories"])]

    if f["neighborhoods"]:
        out = out[out["neighborhood_display"].isin(f["neighborhoods"])]

    lo, hi = f["score_range"]
    out = out[(out["ai_readiness_score"] >= lo) & (out["ai_readiness_score"] <= hi)]

    if f["has_whatsapp"]:
        # Either explicit whatsapp_flag or any phone present
        has_phone = (
            out["phone_e164"].notna() | out.get("phone_raw", pd.Series(dtype=object)).notna()
        )
        out = out[has_phone | (out["whatsapp_flag"] == True)]  # noqa: E712

    if f["has_instagram"]:
        out = out[out["instagram_handle"].notna() & (out["instagram_handle"] != "")]

    if f["has_website"]:
        out = out[out["website"].notna() & (out["website"] != "")]

    if f["search"]:
        needle = f["search"].lower().strip()
        out = out[out["name"].fillna("").str.lower().str.contains(needle)]

    return out
