from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class Store:
    slug: str
    display: str
    hosts: tuple[str, ...]
    url_template: str
    sku_pattern: str
    is_grocery: bool
    scrapeable: bool
    pref: int

    def url(self, sku: str) -> str:
        return self.url_template.format(sku=sku) if self.url_template else ''

    def matches_host(self, host: str) -> bool:
        return any(host == h or host.endswith('.' + h) for h in self.hosts)


class StoreRegistry:
    def __init__(self, stores: tuple[Store, ...]):
        self._by_slug = {s.slug: s for s in stores}

    def get(self, slug: str) -> Store | None:
        return self._by_slug.get(slug)

    def resolve(self, slug: str) -> Store:
        return self._by_slug.get(slug) or Store(slug, slug.replace('-', ' ').title(), (), '', '', False, False, _UNRANKED)

    def display(self, slug: str) -> str:
        store = self._by_slug.get(slug)
        return store.display if store else slug.replace('-', ' ').title()

    def display_for_url(self, url: str) -> str:
        if not url:
            return ''
        host = urlparse(url).hostname or ''
        for store in self._by_slug.values():
            if store.matches_host(host):
                return store.display
        return host.removeprefix('www.')

    def url(self, slug: str, sku: str) -> str:
        store = self._by_slug.get(slug)
        return store.url(sku) if store else ''

    def sku_pattern(self, slug: str) -> str:
        store = self._by_slug.get(slug)
        return store.sku_pattern if store else ''

    def scrapeable_slugs(self) -> list[str]:
        return [s.slug for s in self._by_slug.values() if s.scrapeable]

    def grocery_slugs(self) -> set[str]:
        return {s.slug for s in self._by_slug.values() if s.is_grocery}


_UNRANKED = 5

STORES = StoreRegistry((
    Store('noon-minutes', 'Noon Minutes', ('minutes.noon.com',),
          'https://minutes.noon.com/uae-en/now-product/{sku}/', r'/now-product/([^/]+)/', True, True, 0),
    Store('talabat-mart', 'Talabat Mart', ('talabat.com',),
          'https://www.talabat.com/uae/talabat-mart/s/{sku}', '', True, True, 1),
    Store('noon-ae', 'Noon', ('noon.com',),
          'https://www.noon.com/uae-en/x/{sku}/p/', r'/([A-Z0-9]{8,})/p/', False, True, 2),
    Store('amazon-ae', 'Amazon', ('amazon.ae',),
          'https://www.amazon.ae/dp/{sku}', r'/dp/([A-Z0-9]{10})', False, True, 3),
    Store('iherb-ae', 'iHerb', ('iherb.com', 'ae.iherb.com'),
          'https://ae.iherb.com/pr/x/{sku}', r'/pr/[^/]+/(\d+)', False, True, 4),
    Store('carrefour', 'Carrefour', ('carrefouruae.com',),
          'https://www.carrefouruae.com/mafuae/en/product/p/{sku}', r'/p/(\d+)', True, True, _UNRANKED),
    Store('lulu', 'Lulu', ('luluhypermarket.com',),
          '', r'/p/(\d+)/', True, True, _UNRANKED),
    Store('namshi', 'Namshi', ('namshi.com',),
          'https://www.namshi.com/uae-en/search/?q={sku}', r'/([A-Z0-9]{16,})/p/', False, True, _UNRANKED),
    Store('ounass', 'Ounass', ('ounass.ae',),
          'https://www.ounass.ae/search?q={sku}', r'-(\d{6,})_\d+\.html', False, True, _UNRANKED),
    Store('6thstreet', '6th Street', ('6thstreet.com',),
          'https://en-ae.6thstreet.com/catalogsearch/result/?q={sku}', '', False, True, _UNRANKED),
    Store('next', 'Next', ('next.ae',), '', r'/style/[^/]+/([A-Za-z0-9]+)', False, True, _UNRANKED),
    Store('centrepoint', 'Centrepoint', ('centrepointstores.com',), '', '', False, False, _UNRANKED),
    Store('parfum', 'Parfum.ae', ('parfum.ae',), '', '', False, False, _UNRANKED),
))
