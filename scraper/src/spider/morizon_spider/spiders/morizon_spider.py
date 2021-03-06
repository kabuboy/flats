import os
import logging as log
from datetime import datetime, timedelta

import scrapy
from scrapy.utils.log import configure_logging

from morizon_spider.items import MorizonSpiderItem
from common import (
    RAW_DATA_PATH,
    get_process_from_date,
    logs_conf,
    select_newest_date,
)
import columns
from fs_client import FsClient

# otherwise DEBUG gets logged into container
root_logger = log.getLogger()
for handler in root_logger.handlers:
    root_logger.removeHandler(handler)

fs = FsClient()


class MorizonSpider(scrapy.Spider):

    name = "sale"

    def __init__(self, *args, **kwargs):

        # morizon won't display all offers if following pagination
        # introduce chunker variable and chunk all requested offers by price
        # ie first fileter flats with prices 0-500, then 500-1000 etc
        self.chunk_size = 20000
        self.chunker = 0
        self.max_price = 5000000

        # handle previous date args
        self.previous_date = self._read_last_scraping_date().date()
        self.today_str = datetime.now().date().strftime("%d-%m-%Y")
        self.yesterday_str = (datetime.now().date() - timedelta(days=1)).strftime(
            "%d-%m-%Y"
        )
        self.today = datetime.now().date()
        self.yesterday = datetime.now().date() - timedelta(days=1)
        self.start_date = self.previous_date
        # go back one day (to scrape yesterdays offers)
        if self.start_date == self.today:
            self.start_date = self.yesterday
        self.logger.info(f"Setting start_date to {self.start_date}...")
        self.end_date = self.yesterday
        self.logger.info(f"Setting end_date to {self.end_date}...")

        # optimize scraped space by using date filter arg
        date_diff = (self.yesterday - self.start_date).days
        possible_date_selections = [3, 7, 30, 90, 180]
        date_filter = None
        for date_selection in possible_date_selections:
            if date_diff < date_selection:
                date_filter = date_selection
                break

        # format start_urls
        if date_filter is not None:
            self.date_filter_str = f"&ps%5Bdate_filter%5D={date_filter}"
        else:
            self.date_filter_str = ""
        self.logger.info(f"Date diff = {date_diff} days")
        self.logger.info(f'Setting date_filter string to "{self.date_filter_str}"')
        self.url_base = "https://www.morizon.pl/mieszkania"
        self.start_urls = [
            self.url_base
            + f"/?ps%5Bprice_from%5D={self.chunker}&ps%5Bprice_to%5D={self.chunk_size}"
            + self.date_filter_str
        ]

    def parse(self, response):
        """
        Parse one page of offers, single offers are parsed via callback.
        Find all links and their dates on parsed page.
        """
        links_to_scrape = [
            link
            for link in response.xpath(
                "//a[@class='property_link property-url']/@href"
            ).getall()
            if "/oferta/" in link
        ]
        links_to_scrape_dates_raw = response.xpath(
            "//span[@class='single-result__category single-result__category--date']//text()"
        ).getall()

        # format dates
        links_to_scrape_dates = [
            x
            for x in [
                x.replace("\n", "").replace(" ", "") for x in links_to_scrape_dates_raw
            ]
            if len(x) > 0
        ]
        links_to_scrape_dates = [
            x.replace("dzisiaj", self.today_str).replace("wczoraj", self.yesterday_str)
            for x in links_to_scrape_dates
        ]
        if len(links_to_scrape) != len(links_to_scrape_dates):
            raise ValueError("Found more dates than links to scrape on a single page")

        # iterate over links and dates - parse only in predefined date_range
        for link, date in zip(links_to_scrape, links_to_scrape_dates):
            date_datetime = datetime.strptime(date, "%d-%m-%Y").date()
            if date_datetime >= self.start_date and date_datetime <= self.end_date:
                yield scrapy.Request(
                    link, callback=self.parse_offer, errback=self._errback_httpbin
                )

        # look for next page button
        next_page = response.xpath(
            "//a[@class='mz-pagination-number__btn mz-pagination-number__btn--next']/@href"
        ).get()
        if next_page:
            self.crawler.stats.inc_value("paginations_followed")
            next_page = "https://www.morizon.pl" + next_page + self.date_filter_str
            yield scrapy.Request(next_page, callback=self.parse)
        else:
            # if button is not available start scraping next price chunk
            self.chunker += self.chunk_size
            range_low = self.chunker
            range_high = self.chunker + self.chunk_size
            if range_low >= self.max_price:
                raise scrapy.exceptions.CloseSpider(
                    f"{self.max_price} price range reached. Stopping spider"
                )

            # log current range and number of scraped items
            self.logger.info(
                f"Currenly scraping offers in {range_low}-{range_high} zl price range"
            )
            self.logger.info(
                f"Items scraped: {self.crawler.stats.get_value('item_scraped_count')}"
            )

            next_page = (
                self.url_base
                + f"/?ps%5Bprice_from%5D={range_low}&ps%5Bprice_to%5D={range_high}"
                + self.date_filter_str
            )
            yield scrapy.Request(next_page, callback=self.parse)

    def parse_offer(self, response):
        full_info = MorizonSpiderItem()

        self.crawler.stats.inc_value("offers_followed")

        price = response.xpath("//li[@class='paramIconPrice']/em/text()").get()
        if price:
            full_info[columns.PRICE] = (
                price.replace("\xa0", "")
                .replace(",", ".")
                .replace(" ", "")
                .replace("~", "")
            )
        else:  # not interested in offers without price
            self.crawler.stats.inc_value("offers_no_price_followed")
            return

        price_m2 = response.xpath("//li[@class='paramIconPriceM2']/em/text()").get()
        if price_m2:
            full_info[columns.PRICE_M2] = (
                price_m2.replace("\xa0", "")
                .replace(",", ".")
                .replace(" ", "")
                .replace("~", "")
            )

        size = response.xpath("//li[@class='paramIconLivingArea']/em/text()").get()
        if size:
            full_info[columns.SIZE] = (
                size.replace("\xa0", "").replace(",", ".").replace(" ", "")
            )

        room_n = response.xpath("//li[@class='paramIconNumberOfRooms']/em/text()").get()
        if room_n:
            full_info[columns.ROOM_N] = room_n

        title = " ".join(
            response.xpath("//div[@class='col-xs-9']//span/text()").getall()
        ).replace("\n", "")
        full_info[columns.TITLE] = title

        # list of parameters in offer description
        values = response.xpath("//section[@class='propertyParams']//tr/td").getall()
        keys = response.xpath("//section[@class='propertyParams']//tr/th").getall()
        for key, value in zip(keys, values):
            key = key.split("\n")[1].split(":")[0]
            value = value.split("\n")[1].split(" </td>")[0]
            # retirive info only from specified keys:
            if key == "Piętro":
                full_info[columns.FLOOR] = value
            elif key == "Liczba pięter":
                full_info[columns.BUILDING_HEIGHT] = value
            elif key == "Numer oferty":
                full_info[columns.OFFER_ID] = value
            elif key == "Rok budowy":
                full_info[columns.BUILDING_YEAR] = value
            elif key == "Opublikowano":
                # further confirm date is in specified range (morizon bug?)
                value_dt = self._polish_to_datetime(value)
                if value_dt > self.end_date or value_dt < self.start_date:
                    return
                full_info[columns.DATE_ADDED] = value
            elif key == "Zaktualizowano":
                full_info[columns.DATE_REFRESHED] = value
            elif key == "Typ budynku":
                full_info[columns.BUILDING_TYPE] = value
            elif key == "Materiał budowlany":
                full_info[columns.BUILDING_MATERIAL] = value
            elif key == "Rynek":
                full_info[columns.MARKET_TYPE] = value
            elif key == "Stan nieruchomości":
                full_info[columns.FLAT_STATE] = value
            elif key == "Balkon":
                full_info[columns.BALCONY] = value
            elif key == "Taras":
                full_info[columns.TARAS] = value

        # 4 different optional parameters, below list of key value params
        OTHER_PARAMS = [columns.HEATING, columns.CONVINIENCES, columns.MEDIA, columns.EQUIPMENT]
        OTHER_PARAMS_POL = ["Ogrzewanie", "Udogodnienia", "Media", "Wyposażenie"]
        for param_name, pol_name in zip(OTHER_PARAMS, OTHER_PARAMS_POL):
            value = response.xpath(
                f'//h3[text()="{pol_name}"]/following-sibling::p/text()'
            ).get()
            if value:
                full_info[param_name] = value.replace("\n", "")

        lat = response.xpath("//div[@class='GoogleMap']/@data-lat").get()
        lon = response.xpath("//div[@class='GoogleMap']/@data-lng").get()

        # direct?
        if response.xpath("//div[@class='agentOwnerType']/text()").get():
            direct = 1
        else:
            direct = 0

        # description
        desc = " ".join(response.xpath("//div[@class='description']//text()").getall())
        desc_len = len(desc)

        image_link = response.xpath("//img[@id='imageBig']/@src").get()

        stats = " ".join(
            response.xpath("//div[@class='propertyStat']/p/text()").getall()
        )
        stats = [int(s) for s in stats.split() if s.isdigit()]

        full_info[columns.LAT] = lat
        full_info[columns.LON] = lon
        full_info[columns.URL] = response.request.url
        full_info[columns.DIRECT] = direct
        full_info[columns.DESC] = desc
        full_info[columns.DESC_LEN] = desc_len
        full_info[columns.VIEW_COUNT] = stats[0]
        full_info[columns.PROMOTION_COUNTER] = stats[1]
        full_info[columns.IMAGE_LINK] = image_link

        yield full_info

    def _errback_httpbin(self, failure):
        # log all failures
        self.logger.error(repr(failure))

    def _polish_to_datetime(self, date):
        # change polish date format to datetime
        MONTHS_DICT = {
            "stycznia": "1",
            "lutego": "2",
            "marca": "3",
            "kwietnia": "4",
            "maja": "5",
            "czerwca": "6",
            "lipca": "7",
            "sierpnia": "8",
            "września": "9",
            "października": "10",
            "listopada": "11",
            "grudnia": "12",
        }
        date = date.replace("<strong>", "").replace("</strong>", "")
        if date == "dzisiaj":
            date = date.replace("dzisiaj", self.today_str)
        elif date == "wczoraj":
            date = date.replace("wczoraj", self.yesterday_str)
        else:
            for pol, num in MONTHS_DICT.items():
                date = date.replace(pol, num)
            # Add trailing zeros -,-
            date_elements = date.split()
            if len(date_elements[0]) == 1:
                date_elements[0] = "0" + date_elements[0]
            if len(date_elements[1]) == 1:
                date_elements[1] = "0" + date_elements[1]

            date = "-".join(date_elements)

        date = datetime.strptime(date, "%d-%m-%Y").date()
        return date

    def _read_last_scraping_date(self):
        return get_process_from_date("sale", last_date_of="raw")
