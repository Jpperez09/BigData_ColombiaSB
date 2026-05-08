"""Scrapy items for directory spiders — thin wrappers around BusinessRaw fields."""

import scrapy


class DirectoryItem(scrapy.Item):
    source = scrapy.Field()
    source_id = scrapy.Field()
    name = scrapy.Field()
    city = scrapy.Field()
    address_raw = scrapy.Field()
    address_street = scrapy.Field()
    neighborhood = scrapy.Field()
    phone_raw = scrapy.Field()
    whatsapp_flag = scrapy.Field()
    category_raw = scrapy.Field()
    website = scrapy.Field()
    bio_text = scrapy.Field()
    rating = scrapy.Field()
    reviews_count = scrapy.Field()
    instagram_handle = scrapy.Field()
