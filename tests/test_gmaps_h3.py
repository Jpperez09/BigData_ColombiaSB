"""Unit tests for the target-zone H3 grid, cost tracker, and orchestrator.

All tests are offline — no live Google Maps API calls.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scrapers.gmaps.cost import (
    BudgetEstimateExceededError,
    BudgetExceededError,
    CostTracker,
    assert_within_budget,
)
from scrapers.gmaps.h3_grid import (
    H3Cell,
    generate_target_grid,
    radius_for_resolution,
    subdivide_cell,
)
from scrapers.gmaps.scraper import scrape_cells_for_category
from scrapers.gmaps.target_zones import TARGET_ZONES, get_zones, list_all_zone_names

# ---------------------------------------------------------------------------
# Target zones
# ---------------------------------------------------------------------------


def test_medellin_target_zones_exist():
    assert "medellin" in TARGET_ZONES
    assert len(TARGET_ZONES["medellin"]) > 0


def test_bogota_target_zones_exist():
    assert "bogota" in TARGET_ZONES
    assert len(TARGET_ZONES["bogota"]) > 0


def test_every_enabled_zone_has_valid_polygon():
    for city, zones in TARGET_ZONES.items():
        for zone in zones:
            if not zone.enabled:
                continue
            assert len(zone.polygon) >= 3, f"Zone {zone.name} polygon too small"
            for lat, lng in zone.polygon:
                # Colombia rough bounds: 4-12 N, -78 to -67 W
                assert -5.0 < lat < 13.0, f"Bad lat in {city}/{zone.name}"
                assert -82.0 < lng < -65.0, f"Bad lng in {city}/{zone.name}"


def test_every_zone_has_priority_in_range():
    for zones in TARGET_ZONES.values():
        for zone in zones:
            assert zone.priority in (1, 2, 3)


def test_priority_filter():
    p1 = get_zones("medellin", priority_max=1)
    p2 = get_zones("medellin", priority_max=2)
    assert len(p2) >= len(p1)
    assert all(z.priority <= 1 for z in p1)
    assert all(z.priority <= 2 for z in p2)


def test_disabled_zones_excluded_by_default():
    enabled = get_zones("bogota", priority_max=3, only_enabled=True)
    all_zones = get_zones("bogota", priority_max=3, only_enabled=False)
    assert len(enabled) <= len(all_zones)


def test_zone_name_filter():
    name = TARGET_ZONES["medellin"][0].name
    out = get_zones("medellin", priority_max=3, zone_names=[name])
    assert len(out) == 1
    assert out[0].name == name


def test_invalid_city_in_get_zones():
    with pytest.raises(KeyError, match="cali"):
        get_zones("cali")


def test_list_all_zone_names_returns_sorted_unique():
    names = list_all_zone_names()
    assert names == sorted(names)
    assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Grid generation
# ---------------------------------------------------------------------------


def test_medellin_priority1_grid_nonempty():
    cells = generate_target_grid("medellin", resolution=7, priority_max=1)
    assert len(cells) > 0
    assert all(isinstance(c, H3Cell) for c in cells)


def test_bogota_priority1_grid_nonempty():
    cells = generate_target_grid("bogota", resolution=7, priority_max=1)
    assert len(cells) > 0


def test_cells_carry_zone_metadata():
    cells = generate_target_grid("medellin", resolution=7, priority_max=2)
    for c in cells:
        assert c.city_slug == "medellin"
        assert c.zone_name  # non-empty
        assert c.priority in (1, 2)
        # Medellín lat/lng range
        assert 6.0 < c.center_lat < 6.5
        assert -76.0 < c.center_lng < -75.4


def test_grid_is_deterministic_and_sorted():
    a = generate_target_grid("medellin", resolution=7, priority_max=2)
    b = generate_target_grid("medellin", resolution=7, priority_max=2)
    assert [c.cell_id for c in a] == [c.cell_id for c in b]
    keys = [(c.priority, c.zone_name, c.cell_id) for c in a]
    assert keys == sorted(keys)


def test_higher_resolution_yields_more_cells():
    cells_7 = generate_target_grid("medellin", resolution=7, priority_max=2)
    cells_8 = generate_target_grid("medellin", resolution=8, priority_max=2)
    # Resolution 8 cells are ~7× smaller, so we expect at least as many cells
    assert len(cells_8) >= len(cells_7)


def test_priority1_subset_of_priority2():
    p1 = generate_target_grid("medellin", resolution=7, priority_max=1)
    p2 = generate_target_grid("medellin", resolution=7, priority_max=2)
    p1_zones = {c.zone_name for c in p1}
    p2_zones = {c.zone_name for c in p2}
    assert p1_zones.issubset(p2_zones)


# ---------------------------------------------------------------------------
# Radius helper
# ---------------------------------------------------------------------------


def test_radius_decreases_with_resolution():
    assert radius_for_resolution(7) > radius_for_resolution(8)
    assert radius_for_resolution(8) > radius_for_resolution(9)
    assert radius_for_resolution(9) > radius_for_resolution(10)


def test_radius_in_expected_range():
    assert 1200 <= radius_for_resolution(7) <= 1600
    assert 700 <= radius_for_resolution(8) <= 900
    assert 300 <= radius_for_resolution(9) <= 500


def test_radius_fallback_positive():
    assert radius_for_resolution(11) > 0


# ---------------------------------------------------------------------------
# Subdivision
# ---------------------------------------------------------------------------


def test_subdivide_returns_higher_resolution_children():
    cells = generate_target_grid("medellin", resolution=7, priority_max=1)
    parent = cells[0].cell_id
    children = subdivide_cell(parent, child_resolution=8)
    assert len(children) > 0
    assert children == sorted(children)
    assert parent not in children


# ---------------------------------------------------------------------------
# Cost tracker
# ---------------------------------------------------------------------------


def test_cost_tracker_starts_at_zero():
    assert CostTracker().total_usd == 0.0


def test_record_nearby_search_adds_cost():
    ct = CostTracker()
    ct.record_nearby_search(city="medellin", zone="el_poblado", category="restaurants")
    assert ct.total_usd > 0


def test_record_place_details_adds_cost():
    ct = CostTracker()
    ct.record_place_details(city="medellin", zone="el_poblado", category="restaurants")
    assert ct.total_usd > 0


def test_zone_breakdown_records_each_call():
    ct = CostTracker()
    ct.record_nearby_search(city="bogota", zone="parque_93", category="bakeries")
    ct.record_place_details(city="bogota", zone="parque_93", category="bakeries")
    breakdown = ct.zone_breakdown()
    key = ("bogota", "parque_93", "bakeries")
    assert breakdown[key]["nearby_calls"] == 1
    assert breakdown[key]["details_calls"] == 1


def test_budget_exceeded_raises():
    ct = CostTracker(cap_usd=0.01)
    with pytest.raises(BudgetExceededError):
        ct.record_nearby_search()


def test_estimate_returns_low_mid_high():
    est = CostTracker.estimate(n_nearby_calls=100)
    assert est["nearby_calls"] == 100
    assert est["cost_low"] < est["cost_mid"] < est["cost_high"]


def test_estimate_zero_calls_is_zero_cost():
    est = CostTracker.estimate(0)
    assert est["cost_mid"] == 0.0


def test_assert_within_budget_passes_when_under():
    est = CostTracker.estimate(50)
    assert_within_budget(est, cap_usd=275.0)  # should not raise


def test_assert_within_budget_raises_when_over():
    est = CostTracker.estimate(100_000)
    with pytest.raises(BudgetEstimateExceededError):
        assert_within_budget(est, cap_usd=275.0)


def test_assert_within_budget_force_bypasses_guard():
    est = CostTracker.estimate(100_000)
    assert_within_budget(est, cap_usd=275.0, force=True)  # should not raise


# ---------------------------------------------------------------------------
# Orchestrator — saturation, dedup, budget
# ---------------------------------------------------------------------------

_FAKE_DETAILS = {
    "place_id": "ChIJfake",
    "name": "Fake Place",
    "formatted_address": "Cra 45, Medellín, Colombia",
    "geometry": {"location": {"lat": 6.22, "lng": -75.57}},
    "formatted_phone_number": "300 123 4567",
    "rating": 4.0,
    "user_ratings_total": 25,
    "type": ["restaurant"],
    "website": None,
}


def _details_for(place_id: str) -> dict:
    return {**_FAKE_DETAILS, "place_id": place_id, "name": f"Biz {place_id[-4:]}"}


def _make_cells(n: int) -> list[H3Cell]:
    """Build n synthetic H3Cell objects from the real Medellín grid."""
    cells = generate_target_grid("medellin", resolution=7, priority_max=1)
    return cells[:n]


@patch("scrapers.gmaps.scraper.GMapsClient")
def test_saturation_triggers_subdivision(mock_client):  # noqa: N803
    mock_instance = mock_client.return_value
    saturated = [{"place_id": f"ChIJsat{i:04d}", "name": f"Place {i}"} for i in range(60)]
    call_count = {"n": 0}

    def fake_nearby(location, radius, keyword):
        call_count["n"] += 1
        return saturated if call_count["n"] == 1 else []

    mock_instance.nearby_search.side_effect = fake_nearby
    mock_instance.place_details.return_value = {}

    cells = _make_cells(1)
    seen: set[str] = set()
    scrape_cells_for_category(
        cells,
        "restaurants",
        cost_tracker=CostTracker(),
        seen_place_ids=seen,
        max_resolution=8,
    )
    # Parent + at least one child call
    assert mock_instance.nearby_search.call_count > 1


@patch("scrapers.gmaps.scraper.GMapsClient")
def test_saturation_stops_at_max_resolution(mock_client):  # noqa: N803
    """If max_resolution == base resolution, no subdivision happens."""
    mock_instance = mock_client.return_value
    saturated = [{"place_id": f"ChIJend{i:04d}", "name": f"Place {i}"} for i in range(60)]
    mock_instance.nearby_search.return_value = saturated
    mock_instance.place_details.side_effect = lambda pid: _details_for(pid)

    cells = _make_cells(1)
    seen: set[str] = set()
    scrape_cells_for_category(
        cells,
        "restaurants",
        cost_tracker=CostTracker(),
        seen_place_ids=seen,
        max_resolution=cells[0].resolution,  # equal — no room to subdivide
    )
    # Exactly one Nearby call (no recursion)
    assert mock_instance.nearby_search.call_count == 1


@patch("scrapers.gmaps.scraper.GMapsClient")
def test_seen_place_ids_prevents_duplicate_details(mock_client):  # noqa: N803
    """If a place_id is already in seen_place_ids, no new Place Details call."""
    mock_instance = mock_client.return_value
    mock_instance.nearby_search.return_value = [
        {"place_id": "ChIJalreadyseen", "name": "Already Seen"},
    ]
    mock_instance.place_details.side_effect = lambda pid: _details_for(pid)

    cells = _make_cells(1)
    seen: set[str] = {"ChIJalreadyseen"}  # already fetched in a prior category
    businesses, evidence = scrape_cells_for_category(
        cells,
        "restaurants",
        cost_tracker=CostTracker(),
        seen_place_ids=seen,
    )
    # No new businesses fetched
    assert businesses == []
    # But evidence is still recorded for cross-category attribution
    assert len(evidence) == 1
    assert evidence[0].place_id == "ChIJalreadyseen"
    # No Place Details call
    assert mock_instance.place_details.call_count == 0


@patch("scrapers.gmaps.scraper.GMapsClient")
def test_dedup_across_overlapping_cells(mock_client):  # noqa: N803
    """The same place_id returned by 3 cells should yield only one BusinessRaw."""
    mock_instance = mock_client.return_value
    mock_instance.nearby_search.return_value = [
        {"place_id": "ChIJdupe1", "name": "A"},
        {"place_id": "ChIJdupe2", "name": "B"},
    ]
    mock_instance.place_details.side_effect = lambda pid: _details_for(pid)

    cells = _make_cells(3)
    businesses, evidence = scrape_cells_for_category(
        cells,
        "restaurants",
        cost_tracker=CostTracker(),
        seen_place_ids=set(),
    )
    source_ids = [b.source_id for b in businesses]
    assert len(set(source_ids)) == len(source_ids)  # all unique
    assert len(businesses) == 2  # only 2 unique places
    # Evidence rows are recorded once per cell (no dedup at evidence layer)
    assert len(evidence) == 6  # 2 places × 3 cells


@patch("scrapers.gmaps.scraper.GMapsClient")
def test_evidence_includes_zone_and_category(mock_client):  # noqa: N803
    mock_instance = mock_client.return_value
    mock_instance.nearby_search.return_value = [
        {"place_id": "ChIJev1", "name": "EV 1"},
    ]
    mock_instance.place_details.side_effect = lambda pid: _details_for(pid)

    cells = _make_cells(1)
    _, evidence = scrape_cells_for_category(
        cells,
        "beauty_salons",
        cost_tracker=CostTracker(),
        seen_place_ids=set(),
    )
    assert len(evidence) == 1
    e = evidence[0]
    assert e.category == "beauty_salons"
    assert e.zone_name == cells[0].zone_name
    assert e.city == "medellin"
    assert e.h3_cell  # non-empty


# ---------------------------------------------------------------------------
# Dry-run / estimate helpers
# ---------------------------------------------------------------------------


def test_dry_run_does_not_call_gmaps_api():
    """generate_target_grid + CostTracker.estimate must not import or call googlemaps."""
    # Just verifying these run without any network — pytest will fail if they hit network.
    cells = generate_target_grid("medellin", resolution=7, priority_max=2)
    est = CostTracker.estimate(len(cells) * 15)
    assert est["nearby_calls"] == len(cells) * 15
