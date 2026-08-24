import json
import urllib.parse

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from pkg.scraper.driver import make_browser, new_page, open_page, stealth_for


def fetch_page_text(url: str) -> tuple[str, list[dict]]:
    stealth = stealth_for(url)
    with sync_playwright() as pw:
        browser = make_browser(pw, stealth=stealth)
        try:
            try:
                page = new_page(browser, url, wait_for='networkidle', stealth=stealth)
            except PWTimeout:
                page = new_page(browser, url, wait_for='domcontentloaded', stealth=stealth)
                page.wait_for_timeout(3_000)
            text = page.inner_text('body')
            ld_raw = page.evaluate(r"""() => {
                return [...document.querySelectorAll('script[type="application/ld+json"]')]
                    .map(s => { try { return JSON.parse(s.innerText); } catch { return null; } })
                    .filter(Boolean);
            }""")
            return text, ld_raw if isinstance(ld_raw, list) else []
        finally:
            browser.close()


def search_food_image(query: str) -> str | None:
    search_url = f'https://www.google.com/search?q={urllib.parse.quote_plus(query)}&tbm=isch&hl=en'
    with open_page(search_url, wait_for='domcontentloaded', stealth=True) as page:
        page.wait_for_timeout(3_000)

        gstatic_imgs = page.query_selector_all('img[src*="gstatic.com"]')
        if gstatic_imgs:
            gstatic_imgs[0].click()
            page.wait_for_timeout(2_500)

        js = r"""() => {
            const imgs = [...document.querySelectorAll('img[src]')]
                .map(i => ({src: i.src, w: i.naturalWidth, h: i.naturalHeight}))
                .filter(i =>
                    i.src.startsWith('http') &&
                    !i.src.includes('svg') &&
                    i.w > 100 && i.h > 100
                );
            imgs.sort((a, b) => (b.w * b.h) - (a.w * a.h));
            return JSON.stringify(imgs.map(i => i.src).slice(0, 10));
        }"""
        urls = json.loads(page.evaluate(js))
        return urls[0] if urls else None
