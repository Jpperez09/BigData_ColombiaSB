"""SMB Intel CO — Dashboard entry point (Overview page).

Multi-page Streamlit app. Other pages live in dashboard/pages/.

Run locally:
    invoke dashboard
    # or directly:
    streamlit run dashboard/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import plotly.express as px
import streamlit as st

from dashboard.lib.data import get_data_source_label, load_businesses
from dashboard.lib.filters import apply_filters, render_sidebar_filters

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="SMB Intel CO",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("SMB Intel CO — Overview")
st.caption(
    "Colombian SMBs ranked by their fit for a WhatsApp-based AI sales agent. "
    "Data covers Medellín and Bogotá premium commercial zones."
)

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

df = load_businesses()
filters = render_sidebar_filters(df)
filtered = apply_filters(df, filters)

st.sidebar.caption(f"Source: {get_data_source_label()}")
st.sidebar.caption(f"Showing {len(filtered):,} of {len(df):,} businesses")

if df.empty:
    st.warning(
        "No data available. Run the pipeline first: "
        "`invoke pipeline` (loads gmaps → resolves → scores)."
    )
    st.stop()

# ---------------------------------------------------------------------------
# KPI cards
# ---------------------------------------------------------------------------

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        label="Businesses",
        value=f"{len(filtered):,}",
        delta=(f"of {len(df):,} total" if len(filtered) != len(df) else None),
    )

with col2:
    avg_score = float(filtered["ai_readiness_score"].mean()) if not filtered.empty else 0.0
    st.metric(label="Avg AI Readiness", value=f"{avg_score:.1f}", delta="0–100")

with col3:
    if not filtered.empty and filtered["category_display"].notna().any():
        top_vertical = filtered["category_display"].mode().iloc[0]
        top_count = (filtered["category_display"] == top_vertical).sum()
        st.metric(label="Top vertical", value=str(top_vertical), delta=f"{top_count:,} businesses")
    else:
        st.metric(label="Top vertical", value="—")

with col4:
    if not filtered.empty and filtered["neighborhood_display"].notna().any():
        top_zone = filtered["neighborhood_display"].mode().iloc[0]
        top_zone_count = (filtered["neighborhood_display"] == top_zone).sum()
        st.metric(
            label="Top neighborhood",
            value=str(top_zone),
            delta=f"{top_zone_count:,} businesses",
        )
    else:
        st.metric(label="Top neighborhood", value="—")

st.divider()

# ---------------------------------------------------------------------------
# Score distribution
# ---------------------------------------------------------------------------

st.subheader("AI Readiness Score distribution")
if filtered.empty:
    st.info("No businesses match the current filters.")
else:
    fig = px.histogram(
        filtered,
        x="ai_readiness_score",
        nbins=30,
        color="city" if filtered["city"].nunique() > 1 else None,
        labels={"ai_readiness_score": "Score (0–100)", "count": "Businesses"},
    )
    fig.update_layout(
        margin=dict(l=10, r=10, t=10, b=10),
        height=350,
        bargap=0.05,
    )
    st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Vertical breakdown
# ---------------------------------------------------------------------------

col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Businesses by vertical")
    if not filtered.empty:
        vert_counts = filtered["category_display"].value_counts().reset_index().head(15)
        vert_counts.columns = ["vertical", "count"]
        fig = px.bar(
            vert_counts,
            x="count",
            y="vertical",
            orientation="h",
            labels={"count": "Businesses", "vertical": ""},
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=400)
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)

with col_right:
    st.subheader("Avg score by vertical")
    if not filtered.empty:
        vert_score = (
            filtered.groupby("category_display", dropna=True)["ai_readiness_score"]
            .agg(["mean", "count"])
            .reset_index()
            .sort_values("mean", ascending=False)
            .head(15)
        )
        vert_score.columns = ["vertical", "avg_score", "count"]
        fig = px.bar(
            vert_score,
            x="avg_score",
            y="vertical",
            orientation="h",
            hover_data=["count"],
            labels={"avg_score": "Avg score", "vertical": ""},
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=400)
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, use_container_width=True)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.divider()
st.caption(
    "Use the sidebar to filter. Other pages: **Business Table** (export filtered "
    "view), **Map View** (Folium markers), **Top 500** (ranked download)."
)
