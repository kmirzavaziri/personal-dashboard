import re
import sys
import time
from contextlib import suppress

from playwright.sync_api import Page, TimeoutError as PWTimeout

from pkg.scraper.base import Blocked, Scraper
from pkg.scraper.driver import Product, SearchResult, open_page
from core.store.registry import STORES


class PlaywrightScraper(Scraper):
    slug: str = ''
    stealth: bool = False
    search_wait_ms: int = 0
    search_ready: str = ''
    product_wait_for: str = 'load'
    block_retries: int = 0
    block_cooldown: float = 0.0

    def search_url(self, query: str) -> str:
        raise NotImplementedError

    def parse_search(self, page: Page, limit: int) -> list[SearchResult]:
        raise NotImplementedError

    def extract(self, page: Page, url: str) -> Product:
        raise NotImplementedError

    def _open_page(self, url: str, wait_for: str):
        return open_page(url, wait_for=wait_for, stealth=self.stealth)

    def search(self, query: str, limit: int) -> list[SearchResult]:
        return self._with_backoff(lambda: self._search(query, limit))

    def get_product(self, id_or_url: str) -> Product:
        return self._with_backoff(lambda: self._get_product(id_or_url))

    def _search(self, query: str, limit: int) -> list[SearchResult]:
        with self._open_page(self.search_url(query), 'domcontentloaded') as page:
            if self.search_ready:
                with suppress(PWTimeout):
                    page.wait_for_selector(self.search_ready, timeout=8_000)
            if self.search_wait_ms:
                page.wait_for_timeout(self.search_wait_ms)
            return self.parse_search(page, limit)[:limit]

    def _get_product(self, id_or_url: str) -> Product:
        url, sku = self._resolve(id_or_url)
        with self._open_page(url, self.product_wait_for) as page:
            product = self.extract(page, page.url or url)
            if not product.sku:
                product.sku = sku
            return product

    def _with_backoff(self, action):
        for attempt in range(self.block_retries + 1):
            try:
                return action()
            except Blocked:
                if attempt == self.block_retries:
                    raise
                cooldown = self.block_cooldown * (attempt + 1)
                print(
                    f'  🧊 blocked — cooling down {cooldown / 60:.0f}m then retrying '
                    f'({attempt + 1}/{self.block_retries})…',
                    file=sys.stderr, flush=True,
                )
                time.sleep(cooldown)

    def product_url(self, sku: str) -> str:
        return STORES.url(self.slug, sku)

    def _sku_from_url(self, url: str) -> str:
        pattern = STORES.sku_pattern(self.slug)
        if not pattern:
            return ''
        m = re.search(pattern, url)
        return m.group(1) if m else ''

    def _resolve(self, id_or_url: str) -> tuple[str, str]:
        if id_or_url.startswith('http'):
            return id_or_url, self._sku_from_url(id_or_url) or id_or_url
        return self.product_url(id_or_url), id_or_url
