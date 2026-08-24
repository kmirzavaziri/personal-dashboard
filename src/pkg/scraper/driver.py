import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, Page


@dataclass
class Product:
    title: str
    price: float | None
    url: str
    source: str
    sku: str = ''
    brand: str = ''
    image: str = ''
    raw: dict = field(default_factory=dict)


@dataclass
class SearchResult:
    name: str
    price: float | None
    sku: str
    url: str
    brand: str = ''


_STEALTH_HOSTS: frozenset[str] = frozenset({
    'www.noon.com',
    'minutes.noon.com',
    'www.namshi.com',
    'www.carrefouruae.com',
    'gcc.luluhypermarket.com',
    'www.talabat.com',
    'www.google.com',
})


def stealth_for(url: str) -> bool:
    host = urlparse(url).hostname or ''
    return any(host == h or host.endswith('.' + h) for h in _STEALTH_HOSTS)


def parse_price(text: str) -> float | None:
    m = re.search(r'[\d,]+\.?\d*', text.replace(',', ''))
    return float(m.group().replace(',', '')) if m else None


def parse_size_ml(text: str) -> float | None:
    if not text:
        return None
    total = 0.0
    for num, unit in re.findall(r'(\d+(?:\.\d+)?)\s*(ml|l)\b', text, re.IGNORECASE):
        total += float(num) * (1000 if unit.lower() == 'l' else 1)
    return total or None


USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/124.0.0.0 Safari/537.36'
)

_WEBDRIVER_HIDE_SCRIPT = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"


def make_browser(playwright, stealth: bool):
    if stealth:
        return playwright.chromium.launch(
            channel='chrome',
            headless=True,
            args=['--disable-blink-features=AutomationControlled'],
        )
    return playwright.chromium.launch(headless=True)


def new_page(browser, url: str, wait_for: str, stealth: bool) -> Page:
    ctx = browser.new_context(
        user_agent=USER_AGENT,
        locale='en-US',
        viewport={'width': 1280, 'height': 900},
    )
    if stealth:
        ctx.add_init_script(_WEBDRIVER_HIDE_SCRIPT)
    page = ctx.new_page()
    page.goto(url, wait_until=wait_for, timeout=30_000)
    return page


@contextmanager
def open_page(url: str, wait_for: str, stealth: bool):
    with sync_playwright() as pw:
        browser = make_browser(pw, stealth=stealth)
        try:
            yield new_page(browser, url, wait_for=wait_for, stealth=stealth)
        finally:
            browser.close()
