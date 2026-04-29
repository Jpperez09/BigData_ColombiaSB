"""
CLI loader: Parquet → Supabase (businesses_raw or businesses_canonical).

Usage:
    python -m utils.load_to_supabase --source gmaps --path data/raw/gmaps/medellin.parquet
    python -m utils.load_to_supabase --source gmaps --path data/raw/gmaps/medellin.parquet --dry-run
    python -m utils.load_to_supabase --source gmaps --path data/raw/gmaps/medellin.parquet --batch-size 200
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl
from dotenv import load_dotenv
from loguru import logger
from pydantic import ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential

from utils.models import BusinessCanonical, BusinessRaw
from utils.supabase_client import get_client  # imported here; only CALLED when not dry-run

_TABLE_MODELS: dict[str, type] = {
    "businesses_raw": BusinessRaw,
    "businesses_canonical": BusinessCanonical,
}

_VALID_SOURCES = ["gmaps", "instagram", "paginas_amarillas", "mercado_libre"]
_VALID_TABLES = list(_TABLE_MODELS.keys())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m utils.load_to_supabase",
        description="Validate a Parquet file and upsert it into Supabase.",
    )
    p.add_argument(
        "--source",
        required=True,
        choices=_VALID_SOURCES,
        help="Data source identifier",
    )
    p.add_argument(
        "--path",
        required=True,
        help="Path to the .parquet file",
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=500,
        metavar="N",
        help="Rows per upsert batch (max 1000, default 500)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate only — do NOT insert into Supabase",
    )
    p.add_argument(
        "--table",
        default="businesses_raw",
        choices=_VALID_TABLES,
        help="Target Supabase table (default: businesses_raw)",
    )
    return p


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate_rows(
    df: pl.DataFrame,
    model_cls: type,
) -> tuple[list[dict[str, Any]], list[tuple[int, str]]]:
    """
    Iterate over every row of df, instantiate model_cls, and split into
    valid (serialised dicts) and invalid (index, truncated error message).
    """
    valid_rows: list[dict[str, Any]] = []
    invalid_rows: list[tuple[int, str]] = []
    model_fields = set(model_cls.model_fields.keys())

    for idx, row in enumerate(df.iter_rows(named=True)):
        # Strip columns unknown to the model (extra="forbid" would reject them)
        row_filtered = {k: v for k, v in row.items() if k in model_fields}
        try:
            instance = model_cls(**row_filtered)
            valid_rows.append(instance.model_dump(mode="json", exclude_none=True))
        except (ValidationError, TypeError) as exc:
            msg = str(exc)[:200]
            invalid_rows.append((idx, msg))
            logger.warning(f"Row {idx} inválida: {msg}")

    return valid_rows, invalid_rows


# ---------------------------------------------------------------------------
# Error reporting
# ---------------------------------------------------------------------------


def _write_error_csv(invalid_rows: list[tuple[int, str]], source: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path("data/interim")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"load_errors_{source}_{ts}.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["row_index", "error"])
        writer.writerows(invalid_rows)
    logger.info(f"CSV de errores escrito en: {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Upsert with retry
# ---------------------------------------------------------------------------


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=8),
    reraise=True,
)
def _upsert_batch(client: Any, table: str, batch: list[dict]) -> None:
    client.table(table).upsert(batch, on_conflict="source,source_id").execute()


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _print_summary(
    total: int,
    valid: int,
    invalid: int,
    inserted: int,
    db_errors: int,
    elapsed: float,
    dry_run: bool,
) -> None:
    note = " (DRY-RUN — sin inserción)" if dry_run else ""
    sep = "=" * 54
    print(f"\n{sep}")
    print(f"  RESUMEN DE CARGA{note}")
    print(sep)
    print(f"  Filas leídas      : {total:>10,}")
    print(f"  Válidas           : {valid:>10,}")
    print(f"  Inválidas         : {invalid:>10,}")
    print(f"  Insertadas en DB  : {inserted:>10,}")
    print(f"  Fallidas en DB    : {db_errors:>10,}")
    print(f"  Tiempo total      : {elapsed:>9.2f}s")
    print(f"{sep}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    load_dotenv()

    args = _build_parser().parse_args(argv)
    batch_size = min(args.batch_size, 1000)
    start = time.monotonic()

    # 1. Load parquet
    df = pl.read_parquet(args.path)
    total_rows = len(df)
    logger.info(f"Leídas {total_rows} filas de '{args.path}'")

    # 2. Validate rows against the Pydantic model
    model_cls = _TABLE_MODELS[args.table]
    valid_rows, invalid_rows = _validate_rows(df, model_cls)
    logger.info(
        f"Validación completa — válidas: {len(valid_rows)}, "
        f"inválidas: {len(invalid_rows)}, total: {total_rows}"
    )

    # 3. Write error CSV if any invalid rows found
    if invalid_rows:
        _write_error_csv(invalid_rows, args.source)

    # 4. Upsert to Supabase — get_client() is NOT called in dry-run
    inserted = 0
    db_errors = 0

    if not args.dry_run:
        client = get_client()
        for batch_num, i in enumerate(range(0, len(valid_rows), batch_size), start=1):
            batch = valid_rows[i : i + batch_size]
            try:
                _upsert_batch(client, args.table, batch)
                inserted += len(batch)
                logger.info(
                    f"Batch {batch_num}: {len(batch)} filas upserted "
                    f"(acumulado: {inserted}/{len(valid_rows)})"
                )
            except Exception as exc:
                db_errors += len(batch)
                logger.error(f"Batch {batch_num} falló tras 3 reintentos: {exc}")
    else:
        logger.info("Dry-run activo — Supabase no fue contactado.")

    # 5. Summary table
    _print_summary(
        total=total_rows,
        valid=len(valid_rows),
        invalid=len(invalid_rows),
        inserted=inserted,
        db_errors=db_errors,
        elapsed=time.monotonic() - start,
        dry_run=args.dry_run,
    )

    return 1 if (invalid_rows or db_errors) else 0


if __name__ == "__main__":
    sys.exit(main())
