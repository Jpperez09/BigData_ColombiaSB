"""
Tests for utils.load_to_supabase — no real Supabase calls.

Run with:  pytest tests/test_load_to_supabase.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import polars as pl
import pytest
from pydantic import ValidationError

from utils.models import BusinessRaw

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_row(**overrides) -> dict:
    """Minimal dict that satisfies BusinessRaw required fields."""
    base = {
        "source": "gmaps",
        "source_id": "place_001",
        "name": "Restaurante El Jardín",
        "city": "Medellín",
    }
    base.update(overrides)
    return base


def _make_parquet(tmp_path, rows: list[dict]) -> str:
    """Write a list of row dicts to a parquet file and return the path."""
    df = pl.DataFrame(rows)
    path = tmp_path / "test.parquet"
    df.write_parquet(str(path))
    return str(path)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_parquet(tmp_path):
    """Parquet with 5 valid rows."""
    rows = [_minimal_row(source_id=f"place_{i:04d}") for i in range(5)]
    return _make_parquet(tmp_path, rows)


@pytest.fixture
def large_parquet(tmp_path):
    """Parquet with 1 200 valid rows for batch-size tests."""
    rows = [_minimal_row(source_id=f"place_{i:04d}") for i in range(1200)]
    return _make_parquet(tmp_path, rows)


# ---------------------------------------------------------------------------
# Unit tests — Pydantic model validation (no I/O)
# ---------------------------------------------------------------------------


def test_valid_row_passes_validation():
    business = BusinessRaw(**_minimal_row())
    assert business.source == "gmaps"
    assert business.city == "Medellín"
    assert business.source_id == "place_001"


def test_invalid_phone_caught():
    """Phone without +57 prefix must raise ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        BusinessRaw(**_minimal_row(phone_e164="3001234567"))
    assert "phone_e164" in str(exc_info.value)


def test_invalid_city_caught():
    """City outside {Medellín, Bogotá} must raise ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        BusinessRaw(**_minimal_row(city="Cali"))
    assert "city" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Integration tests — main() with mocked Supabase
# ---------------------------------------------------------------------------


def test_dry_run_does_not_call_supabase(valid_parquet):
    """In --dry-run mode, get_client must never be invoked."""
    with patch("utils.load_to_supabase.get_client") as mock_get_client:
        from utils.load_to_supabase import main

        exit_code = main(["--source", "gmaps", "--path", valid_parquet, "--dry-run"])

    mock_get_client.assert_not_called()
    assert exit_code == 0


def test_batch_size_respected(large_parquet):
    """1 200 rows with batch-size=500 must produce exactly 3 upsert calls."""
    mock_client = MagicMock()

    with patch("utils.load_to_supabase.get_client", return_value=mock_client):
        from utils.load_to_supabase import main

        exit_code = main(
            [
                "--source",
                "gmaps",
                "--path",
                large_parquet,
                "--batch-size",
                "500",
                "--table",
                "businesses_raw",
            ]
        )

    # 500 + 500 + 200 = 3 batches
    upsert_mock = mock_client.table.return_value.upsert
    assert upsert_mock.call_count == 3, f"Expected 3 upsert calls, got {upsert_mock.call_count}"
    assert exit_code == 0
