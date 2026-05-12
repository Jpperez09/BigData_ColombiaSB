"""Scrapy item pipelines for directory spiders.

Pipeline order:
  300 — BusinessRawValidationPipeline: converts DirectoryItem → BusinessRaw,
         drops rows that fail Pydantic validation.
  400 — ParquetWriterPipeline: accumulates validated rows and writes to Parquet
         on spider close.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
from loguru import logger
from pydantic import ValidationError
from scrapy import Spider
from scrapy.exceptions import DropItem

from scrapers.directories.items import DirectoryItem
from utils.models import BusinessRaw

_OUTPUT_DIR = Path("data/raw")


class BusinessRawValidationPipeline:
    """Validate each item as a BusinessRaw instance; drop invalid rows."""

    def process_item(self, item: DirectoryItem, spider: Spider) -> DirectoryItem:
        try:
            BusinessRaw(**{k: v for k, v in item.items()})
        except ValidationError as exc:
            raise DropItem(f"Validation failed for {item.get('source_id')}: {exc}") from exc
        return item


class ParquetWriterPipeline:
    """Collect all valid items and write a single Parquet file on spider close."""

    def open_spider(self, spider: Spider) -> None:
        self._rows: list[dict] = []

    def process_item(self, item: DirectoryItem, spider: Spider) -> DirectoryItem:
        self._rows.append(dict(item))
        return item

    def close_spider(self, spider: Spider) -> None:
        if not self._rows:
            logger.warning(f"{spider.name}: no rows collected — Parquet not written")
            return

        out = _OUTPUT_DIR / spider.name / f"{spider.name}.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)

        validated = []
        for row in self._rows:
            try:
                biz = BusinessRaw(**row)
                validated.append(biz.model_dump())
            except ValidationError as exc:
                logger.warning(f"Skipping row during write: {exc}")

        if validated:
            df = pl.DataFrame(validated)
            df.write_parquet(out)
            logger.info(f"{spider.name}: wrote {len(validated)} rows to {out}")
        else:
            logger.warning(f"{spider.name}: all rows failed validation — Parquet not written")
