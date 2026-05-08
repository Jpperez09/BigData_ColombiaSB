"""Map View page — Folium markers coloured by score quintile."""

from __future__ import annotations

import folium
import streamlit as st
from streamlit_folium import st_folium

from dashboard.lib.data import get_data_source_label, load_businesses
from dashboard.lib.filters import apply_filters, render_sidebar_filters

st.set_page_config(page_title="Map View — SMB Intel", page_icon="🗺️", layout="wide")

st.title("Map View")
st.caption("Marker colour = AI Readiness Score quintile (red = high, blue = low).")

df = load_businesses()
filters = render_sidebar_filters(df)
filtered = apply_filters(df, filters)

st.sidebar.caption(f"Source: {get_data_source_label()}")
st.sidebar.caption(f"Showing {len(filtered):,} of {len(df):,} businesses")

if df.empty:
    st.warning("No data available. Run `invoke pipeline` first.")
    st.stop()

# Drop rows without coordinates
mappable = filtered.dropna(subset=["lat", "lng"])
mappable = mappable[(mappable["lat"] != 0) & (mappable["lng"] != 0)]

if mappable.empty:
    st.info("No businesses with coordinates match the current filters.")
    st.stop()

# Cap markers — Folium gets sluggish past ~1500 pins
MAX_MARKERS = 1500
truncated = len(mappable) > MAX_MARKERS
if truncated:
    mappable = mappable.sort_values("ai_readiness_score", ascending=False).head(MAX_MARKERS)
    st.warning(
        f"Showing top {MAX_MARKERS:,} by score (out of {len(filtered):,}). "
        "Tighten filters in the sidebar to see more."
    )

# ---------------------------------------------------------------------------
# Quintile colouring
# ---------------------------------------------------------------------------

# Bucket scores into 5 colour bands: blue (low) → red (high)
_COLOURS = ["#3182bd", "#6baed6", "#9ecae1", "#fd8d3c", "#e6550d"]
_QUINTILE_LABELS = ["Q1 (lowest)", "Q2", "Q3", "Q4", "Q5 (highest)"]


def _colour_for(score: float) -> str:
    if score < 30:
        return _COLOURS[0]
    if score < 40:
        return _COLOURS[1]
    if score < 50:
        return _COLOURS[2]
    if score < 60:
        return _COLOURS[3]
    return _COLOURS[4]


# ---------------------------------------------------------------------------
# Map centre
# ---------------------------------------------------------------------------

centre_lat = float(mappable["lat"].mean())
centre_lng = float(mappable["lng"].mean())

m = folium.Map(location=[centre_lat, centre_lng], zoom_start=11, tiles="cartodbpositron")

# Marker cluster for performance with many points
from folium.plugins import MarkerCluster  # noqa: E402  (folium-only plugin)

cluster = MarkerCluster(name="Businesses").add_to(m)

for row in mappable.itertuples(index=False):
    score = float(getattr(row, "ai_readiness_score", 0) or 0)
    name = getattr(row, "name", "Unknown")
    category = getattr(row, "category_display", "") or ""
    neighborhood = getattr(row, "neighborhood_display", "") or ""
    rating = getattr(row, "rating", None)
    reviews = getattr(row, "reviews_count", None)
    website = getattr(row, "website", None)
    ig = getattr(row, "instagram_handle", None)

    rating_html = f"⭐ {rating:.1f} ({reviews})" if rating and reviews else "—"
    web_html = f'<a href="{website}" target="_blank">website</a>' if website else ""
    ig_html = f' · <a href="https://instagram.com/{ig}" target="_blank">@{ig}</a>' if ig else ""

    popup_html = (
        f"<b>{name}</b><br>"
        f"{category} · {neighborhood}<br>"
        f"Score: <b>{score:.1f}</b> · {rating_html}<br>"
        f"{web_html}{ig_html}"
    )

    folium.CircleMarker(
        location=[float(row.lat), float(row.lng)],
        radius=5,
        fill=True,
        fill_opacity=0.85,
        color=_colour_for(score),
        fill_color=_colour_for(score),
        weight=1,
        popup=folium.Popup(popup_html, max_width=300),
    ).add_to(cluster)

# Legend (manual HTML overlay)
legend_html = """
<div style="
  position: fixed; bottom: 30px; left: 30px; z-index: 9999;
  background: white; padding: 8px 12px; border-radius: 6px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.15); font-size: 12px;
  font-family: sans-serif;
">
  <b>AI Readiness</b><br>
  <span style="color:#e6550d">●</span> 60+ &nbsp;
  <span style="color:#fd8d3c">●</span> 50–60 &nbsp;
  <span style="color:#9ecae1">●</span> 40–50 <br>
  <span style="color:#6baed6">●</span> 30–40 &nbsp;
  <span style="color:#3182bd">●</span> &lt; 30
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

# Render
st_folium(m, use_container_width=True, height=600, returned_objects=[])
