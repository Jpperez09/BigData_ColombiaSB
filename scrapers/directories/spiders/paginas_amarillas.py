"""Scrapy spider for Páginas Amarillas Colombia (paginasamarillas.com.co).

Scrapes the 15 target verticals across Medellín and Bogotá.
Output: data/raw/directories/paginas_amarillas.parquet via ParquetWriterPipeline.

Run:
    scrapy crawl paginas_amarillas -s JOBDIR=.scrapy/paginas_amarillas
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

_BASE = "https://www.paginasamarillas.com.co"

# Same 15 verticals as the gmaps spider, mapped to PA search slugs
_CATEGORIES = [
    "tiendas-de-ropa",
    "salones-de-belleza",
    "restaurantes",
    "gimnasios",
    "clinicas-dentales",
    "veterinarias",
    "inmobiliarias",
    "fotografos",
    "panaderias",
    "joyerias",
    "opticas",
    "talleres-de-mecanica",
    "servicios-de-limpieza",
    "academias-de-idiomas",
    "centros-de-tutoria",
]

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


class PaginasAmarillasSpider(scrapy.Spider):
    name = "paginas_amarillas"
    allowed_domains = ["paginasamarillas.com.co"]

    custom_settings = {
        "DOWNLOAD_DELAY": 1.5,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 2,
        "ROBOTSTXT_OBEY": False,
        "USER_AGENT": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    }

    def start_requests(self):
        for canonical_city, city_slug in _CITIES.items():
            for category in _CATEGORIES:
                url = f"{_BASE}/search/{category}/{city_slug}/1"
                yield scrapy.Request(
                    url,
                    callback=self.parse_listing,
                    cb_kwargs={"city": canonical_city, "category": category, "page": 1},
                )

    def parse_listing(self, response, city: str, category: str, page: int):
        listings = response.css("div.result-block, div.listing-item, article.listing")

        if not listings:
            logger.debug(f"No listings found: {response.url}")
            return

        for listing in listings:
            yield from self._parse_listing(listing, city, category, response.url)

        # Pagination — follow next page if present
        next_href = response.css("a.next-page::attr(href), a[rel=next]::attr(href)").get()
        if next_href and page < 50:
            yield response.follow(
                next_href,
                callback=self.parse_listing,
                cb_kwargs={"city": city, "category": category, "page": page + 1},
            )

    def _parse_listing(self, sel, city: str, category: str, page_url: str):
        name = sel.css("h2.listing-name::text, h3.listing-name::text, .name::text").get("").strip()
        if not name:
            return

        address_raw = sel.css(".address::text, .direccion::text, span.street::text").get()
        phone_raw = sel.css(".phone::text, .telefono::text, span.tel::text").get()
        website = sel.css("a.website::attr(href), a.web::attr(href)").get()
        bio_text = sel.css(".description::text, .descripcion::text").get()
        neighborhood = sel.css(".neighborhood::text, .barrio::text").get()
        rating_text = sel.css(".rating::text, .stars::attr(data-rating)").get()

        rating = None
        if rating_text:
            try:
                rating = max(0.0, min(5.0, float(rating_text.strip())))
            except ValueError:
                pass

        reviews_text = sel.css(".reviews-count::text, .num-reviews::text").get()
        reviews_count = None
        if reviews_text:
            digits = re.sub(r"[^\d]", "", reviews_text)
            reviews_count = int(digits) if digits else None

        whatsapp_flag = bool(
            _WHATSAPP_RE.search(website or "") or _WHATSAPP_RE.search(bio_text or "")
        )

        instagram_handle = None
        if website:
            match = _INSTAGRAM_RE.search(website)
            if match and match.group(1).lower() not in _IG_RESERVED:
                instagram_handle = match.group(1)

        # Stable source_id from name + city + address
        raw_id = f"{name}|{city}|{address_raw or ''}".lower()
        source_id = hashlib.md5(raw_id.encode()).hexdigest()  # noqa: S324

        yield DirectoryItem(
            source="paginas_amarillas",
            source_id=source_id,
            name=name,
            city=city,
            address_raw=address_raw,
            neighborhood=neighborhood,
            phone_raw=phone_raw,
            whatsapp_flag=whatsapp_flag,
            category_raw=category.replace("-", " "),
            website=website,
            bio_text=bio_text,
            rating=rating,
            reviews_count=reviews_count,
            instagram_handle=instagram_handle,
        )
