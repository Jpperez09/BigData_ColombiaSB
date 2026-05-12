"""Scrapy spider for Mercado Libre Colombia seller pages (mercadolibre.com.co).

Scrapes seller profiles for applicable verticals (clothing, jewelry, optical, etc.)
across Medellín and Bogotá.
Output: data/raw/directories/mercado_libre.parquet via ParquetWriterPipeline.

Run:
    scrapy crawl mercado_libre -s JOBDIR=.scrapy/mercado_libre
"""

from __future__ import annotations

import hashlib
import re

import scrapy
from loguru import logger

from scrapers.directories.items import DirectoryItem

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE = "https://www.mercadolibre.com.co"

# Verticals applicable to ML — chat/catalog-heavy categories
_CATEGORIES = {
    "tiendas-de-ropa": "ropa",
    "joyerias": "joyeria-bisuteria",
    "opticas": "optica",
    "panaderias": "panaderia-reposteria",
    "salones-de-belleza": "belleza-cuidado-personal",
    "fotografos": "fotografia",
}

_CITIES = {
    "Medellín": "medellin",
    "Bogotá": "bogota",
}

_WHATSAPP_RE = re.compile(r"(wa\.me|whatsapp)", re.IGNORECASE)
_INSTAGRAM_RE = re.compile(r"instagram\.com/([A-Za-z0-9_.]+)/?", re.IGNORECASE)
_IG_RESERVED = frozenset({"p", "explore", "accounts", "reel", "reels", "stories", "tv"})

# ---------------------------------------------------------------------------
# Spider
# ---------------------------------------------------------------------------


class MercadoLibreSpider(scrapy.Spider):
    name = "mercado_libre"
    allowed_domains = ["mercadolibre.com.co"]

    custom_settings = {
        "DOWNLOAD_DELAY": 1.5,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
    }

    def start_requests(self):
        for canonical_city, city_slug in _CITIES.items():
            for category_key, category_slug in _CATEGORIES.items():
                url = (
                    f"{_BASE}/tiendas-oficiales/_CityId_{city_slug.upper()}"
                    f"_Category_{category_slug}"
                )
                yield scrapy.Request(
                    url,
                    callback=self.parse_stores,
                    cb_kwargs={
                        "city": canonical_city,
                        "category": category_key,
                        "page": 1,
                    },
                )

    def parse_stores(self, response, city: str, category: str, page: int):
        stores = response.css("li.ui-search-layout__item, div.store-card, article.store-item")

        if not stores:
            logger.debug(f"No stores found: {response.url}")
            return

        for store in stores:
            store_url = store.css("a::attr(href)").get()
            if store_url:
                yield response.follow(
                    store_url,
                    callback=self.parse_store_detail,
                    cb_kwargs={"city": city, "category": category},
                )

        # Pagination
        next_href = response.css("a.andes-pagination__link--next::attr(href)").get()
        if next_href and page < 20:
            yield response.follow(
                next_href,
                callback=self.parse_stores,
                cb_kwargs={"city": city, "category": category, "page": page + 1},
            )

    def parse_store_detail(self, response, city: str, category: str):
        name = (
            response.css(
                "h1.store-header__title::text, h1.seller-name::text, .store-info__name::text"
            )
            .get("")
            .strip()
        )

        if not name:
            logger.debug(f"No name found at {response.url}")
            return

        address_raw = response.css(".store-header__address::text, .seller-location::text").get()

        phone_raw = response.css(".store-contact__phone::text, .contact-phone::text").get()

        website = response.css(
            "a.store-contact__website::attr(href), a.seller-website::attr(href)"
        ).get()

        bio_text = response.css(".store-description__text::text, .seller-description::text").get()

        reviews_text = response.css(
            ".store-header__reviews-count::text, span.review-count::text"
        ).get()
        reviews_count = None
        if reviews_text:
            digits = re.sub(r"[^\d]", "", reviews_text)
            reviews_count = int(digits) if digits else None

        rating_text = response.css(
            "span.store-header__rating::text, span.rating-average::text"
        ).get()
        rating = None
        if rating_text:
            try:
                rating = max(0.0, min(5.0, float(rating_text.strip())))
            except ValueError:
                pass

        whatsapp_flag = bool(
            _WHATSAPP_RE.search(website or "") or _WHATSAPP_RE.search(bio_text or "")
        )

        instagram_handle = None
        social_links = response.css("a[href*='instagram.com']::attr(href)").getall()
        for link in social_links:
            match = _INSTAGRAM_RE.search(link)
            if match and match.group(1).lower() not in _IG_RESERVED:
                instagram_handle = match.group(1)
                break

        # seller_id from URL is the most stable identifier on ML
        url_path = response.url.rstrip("/").split("/")
        source_id = (
            url_path[-1]
            if url_path
            else hashlib.md5(f"{name}|{city}".lower().encode()).hexdigest()  # noqa: S324
        )

        yield DirectoryItem(
            source="mercado_libre",
            source_id=source_id,
            name=name,
            city=city,
            address_raw=address_raw,
            phone_raw=phone_raw,
            whatsapp_flag=whatsapp_flag,
            category_raw=category.replace("-", " "),
            website=website or response.url,
            bio_text=bio_text,
            rating=rating,
            reviews_count=reviews_count,
            instagram_handle=instagram_handle,
        )
