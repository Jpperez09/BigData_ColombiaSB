"""Top 500 page — pre-sorted ranking with one-click CSV download."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from dashboard.lib.data import get_data_source_label, load_businesses
from dashboard.lib.filters import apply_filters, render_sidebar_filters

st.set_page_config(page_title="Top 500 — SMB Intel", page_icon="🏆", layout="wide")

st.title("Top 500 prospects")
st.caption(
    "Top businesses by AI Readiness Score. Use the sidebar filters to narrow "
    "by city, vertical, channel signals, etc., then download the result."
)

df = load_businesses()
filters = render_sidebar_filters(df)
filtered = apply_filters(df, filters).sort_values("ai_readiness_score", ascending=False)

st.sidebar.caption(f"Source: {get_data_source_label()}")
st.sidebar.caption(f"Showing {len(filtered):,} of {len(df):,} businesses")

if df.empty:
    st.warning("No data available. Run `invoke pipeline` first.")
    st.stop()

# Top-N selector
top_n = st.slider(
    "How many to show",
    min_value=10,
    max_value=min(500, max(len(filtered), 10)),
    value=min(500, len(filtered)) if not filtered.empty else 10,
    step=10,
)
top = filtered.head(top_n)

# ---------------------------------------------------------------------------
# Summary stats
# ---------------------------------------------------------------------------

if not top.empty:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            "Score range",
            f"{top['ai_readiness_score'].min():.1f} – {top['ai_readiness_score'].max():.1f}",
        )
    with col2:
        st.metric("Median score", f"{top['ai_readiness_score'].median():.1f}")
    with col3:
        with_phone = top["phone_e164"].notna().sum()
        st.metric("With phone", f"{with_phone:,} ({with_phone/len(top)*100:.0f}%)")

# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------

display_cols = [
    "name",
    "city",
    "category_display",
    "neighborhood_display",
    "ai_readiness_score",
    "rating",
    "reviews_count",
    "phone_e164",
    "website",
    "instagram_handle",
]
present = [c for c in display_cols if c in top.columns]
view = top[present].rename(
    columns={
        "category_display": "category",
        "neighborhood_display": "neighborhood",
        "ai_readiness_score": "score",
        "phone_e164": "phone",
        "instagram_handle": "instagram",
    }
)
view = view.reset_index(drop=True)
view.index = pd.RangeIndex(start=1, stop=len(view) + 1)
view.index.name = "rank"

st.dataframe(
    view,
    use_container_width=True,
    column_config={
        "score": st.column_config.NumberColumn(format="%.1f"),
        "rating": st.column_config.NumberColumn(format="%.1f"),
        "website": st.column_config.LinkColumn(),
    },
    height=600,
)

# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

csv_bytes = view.to_csv(index=True).encode("utf-8")
st.download_button(
    label=f"Download top {len(view):,} as CSV",
    data=csv_bytes,
    file_name=f"smb_intel_top_{len(view)}.csv",
    mime="text/csv",
    type="primary",
)
