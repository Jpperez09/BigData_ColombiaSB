"""Business Table page — filterable / searchable list with CSV export."""

from __future__ import annotations

import streamlit as st

from dashboard.lib.data import get_data_source_label, load_businesses
from dashboard.lib.filters import apply_filters, render_sidebar_filters

st.set_page_config(page_title="Business Table — SMB Intel", page_icon="📋", layout="wide")

st.title("Business Table")
st.caption("Filter in the sidebar, then export the visible rows as CSV.")

df = load_businesses()
filters = render_sidebar_filters(df)
filtered = apply_filters(df, filters).sort_values("ai_readiness_score", ascending=False)

st.sidebar.caption(f"Source: {get_data_source_label()}")
st.sidebar.caption(f"Showing {len(filtered):,} of {len(df):,} businesses")

if df.empty:
    st.warning("No data available. Run `invoke pipeline` first.")
    st.stop()

# ---------------------------------------------------------------------------
# Display columns
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
present_cols = [c for c in display_cols if c in filtered.columns]
view = filtered[present_cols].rename(
    columns={
        "category_display": "category",
        "neighborhood_display": "neighborhood",
        "ai_readiness_score": "score",
        "phone_e164": "phone",
        "instagram_handle": "instagram",
    }
)

# ---------------------------------------------------------------------------
# Table
# ---------------------------------------------------------------------------

st.dataframe(
    view,
    use_container_width=True,
    hide_index=True,
    column_config={
        "score": st.column_config.NumberColumn(format="%.1f"),
        "rating": st.column_config.NumberColumn(format="%.1f"),
        "website": st.column_config.LinkColumn(),
    },
    height=600,
)

# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

csv_bytes = view.to_csv(index=False).encode("utf-8")
st.download_button(
    label=f"Download {len(view):,} rows as CSV",
    data=csv_bytes,
    file_name="smb_intel_filtered.csv",
    mime="text/csv",
)
