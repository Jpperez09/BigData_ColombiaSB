"""Entity resolution pipeline — Step 2.

Merges BusinessRaw rows from all sources into a single deduplicated
businesses_canonical table, assigning a stable master_id to each
real-world entity.

Strategy
--------
1. Load all BusinessRaw parquet files from ``data/raw/``.
2. Normalise names (lowercase, strip accents, remove legal suffixes).
3. Block on two keys independently:
     Block A — exact (city, phone_e164)  — phones don't lie
     Block B — exact (city, name_first_sig_token)  — trigram/prefix on name
4. Within each block: fuzzy-match names with rapidfuzz WRatio >= threshold.
5. Union-Find to merge overlapping match pairs into clusters.
6. Assign master_id = UUID5(DNS, "<city>|<canonical_name_normalised>").
7. Write ``data/clean/businesses_canonical.parquet``.

CLI
---
    python -m scoring.entity_resolution            # default settings
    python -m scoring.entity_resolution --threshold 88 --dry-run
    python -m scoring.entity_resolution --source gmaps  # single source
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
import uuid
from pathlib import Path

import polars as pl
from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RAW_DIR = Path("data/raw")
OUT_PATH = Path("data/clean/businesses_canonical.parquet")

LEGAL_SUFFIXES = re.compile(
    r"\b(s\.?a\.?s\.?|ltda\.?|s\.?a\.?|e\.?u\.?|corp\.?|inc\.?|s\.?c\.?s\.?)\b",
    re.IGNORECASE,
)

# Generic category words that are useless as blocking keys
_STOPWORDS = frozenset(
    {
        "restaurante",
        "restaurant",
        "cafe",
        "cafeteria",
        "cafetería",
        "salon",
        "salón",
        "peluqueria",
        "peluquería",
        "spa",
        "tienda",
        "almacen",
        "almacén",
        "boutique",
        "clinica",
        "clínica",
        "consultorio",
        "gimnasio",
        "gym",
        "bar",
        "bar-restaurante",
        "panaderia",
        "panadería",
        "joyeria",
        "joyería",
        "optica",
        "óptica",
        "veterinaria",
        "veterinario",
        "fotografia",
        "fotografía",
        "academia",
        "instituto",
        "servicio",
        "servicios",
        "empresa",
        "grupo",
        "centro",
        "inmobiliaria",
        "finca",
        "raiz",
        "raíz",
        "taller",
        "el",
        "la",
        "los",
        "las",
        "de",
        "del",
        "y",
    }
)

_FUZZY_THRESHOLD = 85  # WRatio score 0–100; 85 = tight, 80 = loose
_UUID_NAMESPACE = uuid.NAMESPACE_DNS


# ---------------------------------------------------------------------------
# Name normalisation
# ---------------------------------------------------------------------------


def _normalise(name: str) -> str:
    """Lowercase, strip accents, collapse whitespace, remove legal suffixes."""
    # NFD decompose → drop combining marks (accents)
    nfd = unicodedata.normalize("NFD", name)
    ascii_approx = "".join(c for c in nfd if unicodedata.category(c) != "Mn")
    lower = ascii_approx.lower()
    no_legal = LEGAL_SUFFIXES.sub("", lower)
    # Drop residual punctuation left over from stripped suffixes ("s.a.s." → ".")
    no_punct = re.sub(r"[.,;:]+", " ", no_legal)
    return re.sub(r"\s+", " ", no_punct).strip()


def _first_significant_token(name_normalised: str) -> str:
    """Return the first token that isn't a generic category word or stopword."""
    for token in name_normalised.split():
        if token not in _STOPWORDS and len(token) >= 3:
            return token
    # Fallback: just use the full normalised name if everything is a stopword
    return name_normalised


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------


class _UF:
    def __init__(self) -> None:
        self._parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self._parent.setdefault(x, x)
        if self._parent[x] != x:
            self._parent[x] = self.find(self._parent[x])
        return self._parent[x]

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra

    def clusters(self, indices: list[int]) -> dict[int, list[int]]:
        out: dict[int, list[int]] = {}
        for i in indices:
            root = self.find(i)
            out.setdefault(root, []).append(i)
        return out


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _load_all_raw(source_filter: str | None = None) -> pl.DataFrame:
    """Load all BusinessRaw parquet files and stack into one DataFrame."""
    patterns = [
        RAW_DIR / "gmaps" / "*.parquet",
        RAW_DIR / "instagram" / "*.parquet",
    ]
    frames: list[pl.DataFrame] = []
    for pattern in patterns:
        for path in sorted(Path(pattern.parent).glob(pattern.name)):
            if source_filter and source_filter not in path.stem:
                continue
            try:
                df = pl.read_parquet(path)
                frames.append(df)
                logger.debug(f"Loaded {len(df)} rows from {path}")
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Could not read {path}: {exc}")

    if not frames:
        logger.warning("No raw parquet files found.")
        return pl.DataFrame()

    combined = pl.concat(frames, how="diagonal_relaxed")
    logger.info(f"Total raw rows loaded: {len(combined)}")
    return combined


# ---------------------------------------------------------------------------
# Blocking + fuzzy matching
# ---------------------------------------------------------------------------


def _fuzzy_match_block(
    indices: list[int],
    names: list[str],
    threshold: int,
) -> list[tuple[int, int]]:
    """Return (i, j) pairs within the block whose WRatio >= threshold."""
    from rapidfuzz import fuzz

    pairs: list[tuple[int, int]] = []
    for ii in range(len(indices)):
        for jj in range(ii + 1, len(indices)):
            score = fuzz.WRatio(names[ii], names[jj])
            if score >= threshold:
                pairs.append((indices[ii], indices[jj]))
    return pairs


def _resolve(df: pl.DataFrame, threshold: int) -> pl.DataFrame:
    """Add master_id column by blocking + fuzzy matching."""
    n = len(df)
    names_norm: list[str] = df["name_normalised"].to_list()
    cities: list[str] = df["city"].to_list()
    phones: list[str | None] = df["phone_e164"].to_list()
    first_tokens: list[str] = df["name_first_sig_token"].to_list()

    uf = _UF()
    # Initialise all rows as their own root
    for i in range(n):
        uf.find(i)

    # Block A: exact (city, phone_e164) — only non-null phones
    phone_blocks: dict[tuple[str, str], list[int]] = {}
    for i, (city, phone) in enumerate(zip(cities, phones, strict=True)):
        if phone:
            key = (city, phone)
            phone_blocks.setdefault(key, []).append(i)

    for block_indices in phone_blocks.values():
        if len(block_indices) > 1:
            for j in block_indices[1:]:
                uf.union(block_indices[0], j)

    # Block B: (city, name_first_sig_token) — fuzzy match within block
    name_blocks: dict[tuple[str, str], list[int]] = {}
    for i, (city, tok) in enumerate(zip(cities, first_tokens, strict=True)):
        key = (city, tok)
        name_blocks.setdefault(key, []).append(i)

    for block_indices in name_blocks.values():
        if len(block_indices) < 2:
            continue
        block_names = [names_norm[i] for i in block_indices]
        pairs = _fuzzy_match_block(block_indices, block_names, threshold)
        for a, b in pairs:
            uf.union(a, b)

    # Assign master_id per cluster
    clusters = uf.clusters(list(range(n)))
    master_ids: list[str] = [""] * n

    for _root, members in clusters.items():
        # Pick the best representative: longest normalised name in cluster
        rep_idx = max(members, key=lambda i: len(names_norm[i]))
        rep_key = f"{cities[rep_idx]}|{names_norm[rep_idx]}"
        mid = str(uuid.uuid5(_UUID_NAMESPACE, rep_key))
        for m in members:
            master_ids[m] = mid

    return df.with_columns(pl.Series("master_id", master_ids))


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run(
    threshold: int = _FUZZY_THRESHOLD,
    source_filter: str | None = None,
    dry_run: bool = False,
) -> pl.DataFrame:
    raw = _load_all_raw(source_filter)
    if raw.is_empty():
        logger.error("Nothing to resolve.")
        return raw

    # Ensure name_normalised column
    if "name_normalised" not in raw.columns or raw["name_normalised"].is_null().all():
        raw = raw.with_columns(
            pl.col("name").map_elements(_normalise, return_dtype=pl.Utf8).alias("name_normalised")
        )
    else:
        raw = raw.with_columns(
            pl.col("name_normalised").fill_null(
                pl.col("name").map_elements(_normalise, return_dtype=pl.Utf8)
            )
        )

    raw = raw.with_columns(
        pl.col("name_normalised")
        .map_elements(_first_significant_token, return_dtype=pl.Utf8)
        .alias("name_first_sig_token")
    )

    logger.info(f"Running entity resolution: threshold={threshold}")
    resolved = _resolve(raw, threshold)

    n_clusters = resolved["master_id"].n_unique()
    logger.info(
        f"Resolution complete: {len(resolved)} rows → {n_clusters} unique entities "
        f"({len(resolved) - n_clusters} duplicates merged)"
    )

    # Select canonical output columns (drop helpers)
    out = resolved.drop(["name_first_sig_token"], strict=False)

    if dry_run:
        import sys

        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows-safe
        print(out.select(["name", "city", "source", "master_id"]).head(20))
        logger.info("Dry run — no file written.")
        return out

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(str(OUT_PATH))
    logger.info(f"Wrote {len(out)} rows → {OUT_PATH}")
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m scoring.entity_resolution",
        description="Merge all raw business rows into a deduplicated canonical table.",
    )
    p.add_argument(
        "--threshold",
        type=int,
        default=_FUZZY_THRESHOLD,
        metavar="N",
        help=f"WRatio fuzzy-match threshold 0–100 (default {_FUZZY_THRESHOLD}).",
    )
    p.add_argument(
        "--source",
        default=None,
        metavar="SRC",
        help="Filter to files whose path contains this string (e.g. 'gmaps').",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print first 20 resolved rows; do not write parquet.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    run(threshold=args.threshold, source_filter=args.source, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
