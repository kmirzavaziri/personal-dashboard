from abc import ABC, abstractmethod

from pkg.scraper.driver import Product, SearchResult


class Blocked(Exception):
    pass


class Scraper(ABC):
    @abstractmethod
    def search(self, query: str, limit: int) -> list[SearchResult]:
        ...

    @abstractmethod
    def get_product(self, id_or_url: str) -> Product:
        ...

    @abstractmethod
    def product_url(self, sku: str) -> str:
        ...
