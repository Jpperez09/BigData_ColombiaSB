"""Per-call cost estimation and budget enforcement for the GMaps spider.

Google Places API pricing (SKU-based, 2024):
  Nearby Search (Basic):     $0.032 / call
  Place Details (Basic):     $0.017 / call
  Place Details (Contact):   $0.003 / call  (phone + website fields)

We request Basic + Contact, so each Place Details call costs $0.020.

Budget defaults (working plan):
  Hard stop:               $275  (override with ``--budget-cap-usd`` or env)
  Warning thresholds:      $150 / $200 / $225  (logged once each)
  Recommended target run:  $180 – $230
"""

from __future__ import annotations

import threading
from pathlib import Path

from loguru import logger

# ---------------------------------------------------------------------------
# Per-call cost constants (USD)
# ---------------------------------------------------------------------------
NEARBY_COST: float = 0.032
DETAILS_COST: float = 0.017 + 0.003  # Basic + Contact

# ---------------------------------------------------------------------------
# Budget defaults
# ---------------------------------------------------------------------------
DEFAULT_CAP_USD: float = 275.0
WARNING_THRESHOLDS: tuple[float, ...] = (150.0, 200.0, 225.0)

_COST_LOG: Path = Path("logs/gmaps_cost.log")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class BudgetExceededError(RuntimeError):
    """Raised when accumulated estimated spend reaches the configured cap."""


class BudgetEstimateExceededError(RuntimeError):
    """Raised when the pre-run estimate exceeds the cap and ``force=False``."""


# ---------------------------------------------------------------------------
# CostTracker
# ---------------------------------------------------------------------------
class CostTracker:
    """Thread-safe running cost accumulator with hard-stop enforcement.

    Records per-(city, zone, category) breakdown so a session can produce a
    meaningful end-of-run report.
    """

    def __init__(self, cap_usd: float = DEFAULT_CAP_USD) -> None:
        self._lock = threading.Lock()
        self._total: float = 0.0
        self._cap: float = cap_usd
        self._nearby_calls: int = 0
        self._details_calls: int = 0
        self._warned_at: set[float] = set()
        self._per_zone: dict[tuple[str, str, str], dict[str, int]] = {}

    # -- properties -----------------------------------------------------
    @property
    def total_usd(self) -> float:
        with self._lock:
            return self._total

    @property
    def cap_usd(self) -> float:
        return self._cap

    # -- recording ------------------------------------------------------
    def record_nearby_search(
        self,
        city: str | None = None,
        zone: str | None = None,
        category: str | None = None,
    ) -> None:
        """Charge for one Nearby Search; raise ``BudgetExceededError`` if over cap."""
        with self._lock:
            self._nearby_calls += 1
            self._bump_zone(city, zone, category, "nearby_calls", 1)
        self._add(NEARBY_COST)

    def record_place_details(
        self,
        city: str | None = None,
        zone: str | None = None,
        category: str | None = None,
    ) -> None:
        """Charge for one Place Details call; raise ``BudgetExceededError`` if over cap."""
        with self._lock:
            self._details_calls += 1
            self._bump_zone(city, zone, category, "details_calls", 1)
        self._add(DETAILS_COST)

    # -- inspection -----------------------------------------------------
    def summary(self) -> str:
        with self._lock:
            return (
                f"${self._total:.4f} USD "
                f"(nearby={self._nearby_calls}, details={self._details_calls}, "
                f"cap=${self._cap:.2f})"
            )

    def zone_breakdown(self) -> dict[tuple[str, str, str], dict[str, int]]:
        """Return per-(city, zone, category) call counts (copy)."""
        with self._lock:
            return {k: dict(v) for k, v in self._per_zone.items()}

    # -- pre-run estimation --------------------------------------------
    @staticmethod
    def estimate(
        n_nearby_calls: int,
        avg_results_per_call: int = 12,
        dedup_factor: float = 0.7,
    ) -> dict[str, float]:
        """Compute low/mid/high estimates for a given number of Nearby Search calls.

        Args:
            n_nearby_calls:        Total Nearby Search calls (cells * categories).
            avg_results_per_call:  Expected raw places per Nearby Search.
            dedup_factor:          Fraction of those that become NEW Place Details
                                   calls after cross-category deduplication.

        Returns dict with keys: nearby_calls, details_calls_{low,mid,high},
        cost_{low,mid,high}.
        """
        nearby_cost = n_nearby_calls * NEARBY_COST
        base = n_nearby_calls * avg_results_per_call * dedup_factor
        d_low = int(base * 0.6)
        d_mid = int(base)
        d_high = int(base * 1.4)
        return {
            "nearby_calls": n_nearby_calls,
            "details_calls_low": d_low,
            "details_calls_mid": d_mid,
            "details_calls_high": d_high,
            "cost_low": nearby_cost + d_low * DETAILS_COST,
            "cost_mid": nearby_cost + d_mid * DETAILS_COST,
            "cost_high": nearby_cost + d_high * DETAILS_COST,
        }

    # -- private --------------------------------------------------------
    def _add(self, amount: float) -> None:
        crossed: list[float] = []
        with self._lock:
            self._total += amount
            total = self._total
            for t in WARNING_THRESHOLDS:
                if total >= t and t not in self._warned_at:
                    self._warned_at.add(t)
                    crossed.append(t)

        for t in crossed:
            logger.warning(f"Cost threshold ${t:.0f} reached (current ${total:.2f})")

        self._write_log(amount)
        if total >= self._cap:
            raise BudgetExceededError(
                f"Estimated spend ${total:.4f} reached cap ${self._cap:.2f}. Halting."
            )

    def _bump_zone(
        self,
        city: str | None,
        zone: str | None,
        category: str | None,
        key: str,
        delta: int,
    ) -> None:
        if city is None and zone is None and category is None:
            return
        k = (city or "", zone or "", category or "")
        bucket = self._per_zone.setdefault(k, {"nearby_calls": 0, "details_calls": 0})
        bucket[key] = bucket.get(key, 0) + delta

    def _write_log(self, amount: float) -> None:
        _COST_LOG.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            total = self._total
            nearby = self._nearby_calls
            details = self._details_calls
        line = (
            f"added=${amount:.4f} total=${total:.4f} "
            f"nearby_calls={nearby} details_calls={details}\n"
        )
        try:
            with open(_COST_LOG, "a", encoding="utf-8") as fh:
                fh.write(line)
        except OSError as exc:
            logger.warning(f"Could not write cost log: {exc}")


# ---------------------------------------------------------------------------
# Pre-run guard
# ---------------------------------------------------------------------------
def assert_within_budget(estimate: dict[str, float], cap_usd: float, force: bool = False) -> None:
    """Raise BudgetEstimateExceededError if mid-estimate exceeds cap.

    Pass ``force=True`` to bypass (useful when you've authorised a bigger spend
    and want to proceed anyway).
    """
    if estimate["cost_mid"] > cap_usd and not force:
        raise BudgetEstimateExceededError(
            f"Estimated mid-spend ${estimate['cost_mid']:.2f} exceeds cap "
            f"${cap_usd:.2f}. Pass --force-over-budget to proceed, or reduce "
            "scope (priority-max, zones, categories, --limit-hexes)."
        )
