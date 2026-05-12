"""Tests for directory spiders using saved HTML fixtures — no live network."""

from __future__ import annotations

from pathlib import Path

from scrapy.http import HtmlResponse

from scrapers.directories.spiders.mercado_libre import MercadoLibreSpider
from scrapers.directories.spiders.paginas_amarillas import PaginasAmarillasSpider

FIXTURES = Path(__file__).parent / "fixtures"


def _fake_response(fixture_file: str, url: str) -> HtmlResponse:
    """Build a Scrapy HtmlResponse from a local HTML fixture file."""
    html = (FIXTURES / fixture_file).read_bytes()
    return HtmlResponse(url=url, body=html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Páginas Amarillas
# ---------------------------------------------------------------------------


class TestPaginasAmarillasSpider:
    def setup_method(self):
        self.spider = PaginasAmarillasSpider()
        self.response = _fake_response(
            "paginas_amarillas_listing.html",
            "https://www.paginasamarillas.com.co/search/panaderias/medellin/1",
        )

    def _items(self):
        return list(
            self.spider._parse_listing(sel, "Medellín", "panaderias", self.response.url)
            for sel in self.response.css("div.result-block")
        )

    def test_extracts_two_listings(self):
        items = [item for sublist in self._items() for item in sublist]
        assert len(items) == 2

    def test_name_extracted(self):
        items = [item for sublist in self._items() for item in sublist]
        names = [i["name"] for i in items]
        assert "Panadería La Mejor" in names

    def test_city_set_correctly(self):
        items = [item for sublist in self._items() for item in sublist]
        assert all(i["city"] == "Medellín" for i in items)

    def test_source_is_paginas_amarillas(self):
        items = [item for sublist in self._items() for item in sublist]
        assert all(i["source"] == "paginas_amarillas" for i in items)

    def test_source_id_not_null(self):
        items = [item for sublist in self._items() for item in sublist]
        assert all(i["source_id"] for i in items)

    def test_whatsapp_detected_in_bio(self):
        items = [item for sublist in self._items() for item in sublist]
        panaderia = next(i for i in items if "Panadería" in i["name"])
        assert panaderia["whatsapp_flag"] is True

    def test_instagram_handle_extracted_from_website(self):
        items = [item for sublist in self._items() for item in sublist]
        salon = next(i for i in items if "Glamour" in i["name"])
        assert salon["instagram_handle"] == "glamour_medellin"

    def test_rating_parsed_as_float(self):
        items = [item for sublist in self._items() for item in sublist]
        panaderia = next(i for i in items if "Panadería" in i["name"])
        assert panaderia["rating"] == 4.2

    def test_reviews_count_parsed_as_int(self):
        items = [item for sublist in self._items() for item in sublist]
        panaderia = next(i for i in items if "Panadería" in i["name"])
        assert panaderia["reviews_count"] == 38


# ---------------------------------------------------------------------------
# Mercado Libre
# ---------------------------------------------------------------------------


class TestMercadoLibreSpider:
    def setup_method(self):
        self.spider = MercadoLibreSpider()
        self.response = _fake_response(
            "mercado_libre_store.html",
            "https://www.mercadolibre.com.co/tiendas-oficiales/joyeria-dorada",
        )

    def _item(self):
        items = list(
            self.spider.parse_store_detail(self.response, city="Bogotá", category="joyerias")
        )
        assert len(items) == 1
        return items[0]

    def test_name_extracted(self):
        assert self._item()["name"] == "Joyería Dorada"

    def test_city_set_correctly(self):
        assert self._item()["city"] == "Bogotá"

    def test_source_is_mercado_libre(self):
        assert self._item()["source"] == "mercado_libre"

    def test_source_id_not_null(self):
        assert self._item()["source_id"]

    def test_rating_parsed(self):
        assert self._item()["rating"] == 4.5

    def test_reviews_count_parsed(self):
        assert self._item()["reviews_count"] == 213

    def test_instagram_handle_extracted(self):
        assert self._item()["instagram_handle"] == "joyeria_dorada"

    def test_phone_extracted(self):
        assert self._item()["phone_raw"] == "601 345 6789"

    def test_address_extracted(self):
        assert "Cll 72" in self._item()["address_raw"]
