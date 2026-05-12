"""Shared Scrapy settings for all directory spiders."""

from utils.config import get_settings

_cfg = get_settings()

BOT_NAME = "smb-intel-co"

SPIDER_MODULES = ["scrapers.directories.spiders"]
NEWSPIDER_MODULE = "scrapers.directories.spiders"

ROBOTSTXT_OBEY = True

DOWNLOAD_DELAY = 1.5
CONCURRENT_REQUESTS_PER_DOMAIN = 2
CONCURRENT_REQUESTS = 4
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.5

USER_AGENT = _cfg.SCRAPY_USER_AGENT

FEEDS = {}  # output handled by the Parquet pipeline

ITEM_PIPELINES = {
    "scrapers.directories.pipelines.BusinessRawValidationPipeline": 300,
    "scrapers.directories.pipelines.ParquetWriterPipeline": 400,
}

REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
LOG_LEVEL = "INFO"
