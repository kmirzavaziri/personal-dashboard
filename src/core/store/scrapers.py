import json
import re
import urllib.parse
import urllib.request
from contextlib import contextmanager, suppress
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PWTimeout

from pkg.scraper.base import Blocked, Scraper
from pkg.scraper.cdp import CdpBrowser
from pkg.scraper.ratelimit import RateLimiter
from pkg.scraper.driver import (
    Product,
    SearchResult,
    USER_AGENT,
    open_page,
    parse_price,
    parse_size_ml,
)
from core.store.base import PlaywrightScraper
from core.store.registry import STORES


class NoonMinutesScraper(PlaywrightScraper):
    slug = 'noon-minutes'
    stealth = True
    search_wait_ms = 3_000

    def search_url(self, query: str) -> str:
        return f'https://minutes.noon.com/uae-en/search/?q={urllib.parse.quote_plus(query)}'

    def parse_search(self, page: Page, limit: int) -> list[SearchResult]:
        js = r"""() => {
            const links = [...document.querySelectorAll('a[href*="/now-product/"]')];
            return JSON.stringify(links.map(a => {
                const href = a.href;
                const skuMatch = href.match(/\/now-product\/([^/]+)\//);
                const sku = skuMatch ? skuMatch[1] : '';

                const skip = new Set(['add', 'imported']);
                const lines = (a.innerText || '').split('\n')
                    .map(l => l.trim()).filter(l => l && !skip.has(l.toLowerCase())
                        && !/^-?\d+%$/.test(l));

                const title = lines.find(l =>
                    /[a-zA-Z]/.test(l) &&
                    !(l === l.toUpperCase() && l.length <= 12 && /^[A-Z][A-Z\s]+$/.test(l))
                ) || lines[0] || '';

                let price = '';
                for (let i = lines.length - 1; i >= 0; i--) {
                    if (/^\d[\d.]*$/.test(lines[i])) { price = lines[i]; break; }
                }

                return {sku, title, price, href};
            }).filter(r => r.sku && r.title));
        }"""
        raw = json.loads(page.evaluate(js))
        seen: set[str] = set()
        results = []
        for r in raw:
            if r['sku'] in seen:
                continue
            seen.add(r['sku'])
            results.append(SearchResult(
                name=r['title'],
                price=float(r['price']) if r.get('price') else None,
                sku=r['sku'],
                url=r['href'],
            ))
        return results

    def extract(self, page: Page, url: str) -> Product:
        try:
            page.wait_for_selector('[class*="expandButton"]', timeout=6_000)
            page.wait_for_timeout(1_500)
            btn = page.query_selector('[class*="expandButton"]')
            if btn:
                btn.scroll_into_view_if_needed()
                btn.click()
                page.wait_for_timeout(800)
        except Exception:
            pass

        js = r"""() => {
            const lds = [...document.querySelectorAll('script[type="application/ld+json"]')]
                .map(s => { try { return JSON.parse(s.innerText); } catch { return null; } })
                .filter(Boolean);
            const prod = lds.find(l => l['@type'] === 'Product');
            if (!prod) return JSON.stringify({});
            const offer = Array.isArray(prod.offers) ? prod.offers[0] : prod.offers;

            const nutrition = {};
            const header = document.querySelector('[class*="NutritionInfo"] [class*="columnHeader"]')?.innerText?.trim() || 'per 100g';
            document.querySelectorAll('[class*="NutritionInfo"] table tr').forEach(row => {
                const cells = row.querySelectorAll('td');
                if (cells.length >= 2) {
                    const name = cells[0].innerText?.trim();
                    let val = cells[1].innerText?.trim();
                    if (cells.length >= 3) {
                        const unit = cells[2].innerText?.trim();
                        if (unit) val = `${val} ${unit}`;
                    }
                    if (name && val) nutrition[name] = val;
                }
            });

            const noteEl = [...document.querySelectorAll('[class*="NutritionInfo"] *')]
                .find(el => el.children.length === 0 && /serving size/i.test(el.textContent || ''));
            const noteText = (noteEl?.textContent || noteEl?.innerText || '').trim();
            const gramsMatch = noteText.match(/serving size.*?(\d+(?:\.\d+)?\s*g)/i);
            const servingGrams = gramsMatch ? gramsMatch[1].replace(/\s+/g, '') : '';
            const nutrition_per = servingGrams ? `per serving (${servingGrams})` : header;

            let pageSize = '';
            const sizeRe = /^\d+(?:\.\d+)?\s*(?:ml|l|g|kg)$/i;
            for (const el of document.querySelectorAll('body *')) {
                if (el.childElementCount === 0) {
                    const t = (el.textContent || '').trim();
                    if (sizeRe.test(t)) { pageSize = t; break; }
                }
            }

            return JSON.stringify({
                title:        prod.name || '',
                price:        offer?.price != null ? String(offer.price) : '',
                sku:          prod.sku || '',
                brand:        prod.brand?.name || '',
                image:        Array.isArray(prod.image) ? prod.image[0] : (prod.image || ''),
                description:  prod.description || '',
                pageSize,
                nutrition,
                nutrition_per,
            });
        }"""
        data = json.loads(page.evaluate(js))
        size_ml = parse_size_ml(data.get('pageSize', '')) or parse_size_ml(
            f"{data.get('title', '')} {data.get('description', '')}"
        )
        if size_ml:
            data['size_ml'] = size_ml
        return Product(
            title=data.get('title') or '',
            price=float(data['price']) if data.get('price') else None,
            url=url,
            source='noon_minutes',
            sku=data.get('sku', ''),
            brand=data.get('brand', ''),
            image=data.get('image', ''),
            raw=data,
        )


class NoonUAEScraper(PlaywrightScraper):
    slug = 'noon-ae'
    stealth = True
    search_wait_ms = 4_000

    def search_url(self, query: str) -> str:
        return f'https://www.noon.com/uae-en/search/?q={urllib.parse.quote_plus(query)}'

    def parse_search(self, page: Page, limit: int) -> list[SearchResult]:
        js = r"""() => {
            const links = [...document.querySelectorAll('a[href*="/uae-en/"][href*="/p/"]')];
            return JSON.stringify(links.map(a => {
                const href = a.href;
                const idMatch = href.match(/\/([A-Z0-9]{8,})\/p\//);
                const sku = idMatch ? idMatch[1] : '';

                const rawLines = (a.innerText?.trim() || '').split('\n').map(l => l.trim()).filter(Boolean);
                const title = rawLines.find(l =>
                    /[a-zA-Z]/.test(l) &&
                    !/^-?\d+%$/.test(l) &&
                    !(l === l.toUpperCase() && l.length <= 12 && /^[A-Z][A-Z\s]+$/.test(l))
                ) || rawLines[0] || '';

                let priceText = '';
                let el = a;
                for (let i = 0; i < 6; i++) {
                    el = el.parentElement;
                    if (!el) break;
                    const pEl = el.querySelector('[class*="price"]');
                    if (pEl) { priceText = pEl.innerText?.trim(); break; }
                }
                const priceMatch = priceText.match(/[\d.]+/);
                const price = priceMatch ? priceMatch[0] : '';

                return {sku, title, price, href};
            }).filter(r => r.sku && r.title));
        }"""
        raw = json.loads(page.evaluate(js))
        seen: set[str] = set()
        results = []
        for r in raw:
            if r['sku'] in seen:
                continue
            seen.add(r['sku'])
            results.append(SearchResult(
                name=r['title'],
                price=float(r['price']) if r.get('price') else None,
                sku=r['sku'],
                url=r['href'],
            ))
        return results

    def extract(self, page: Page, url: str) -> Product:
        js = r"""() => {
            const lds = [...document.querySelectorAll('script[type="application/ld+json"]')]
                .map(s => { try { return JSON.parse(s.innerText); } catch { return null; } })
                .filter(Boolean);
            const prod = lds.find(l => l['@type'] === 'Product');
            if (!prod) return JSON.stringify({});
            const offer = Array.isArray(prod.offers) ? prod.offers[0] : prod.offers;
            return JSON.stringify({
                title:    prod.name || '',
                price:    offer?.price ? String(offer.price) : (prod.price ? String(prod.price) : ''),
                sku:      prod.sku || '',
                brand:    prod.brand?.name || '',
                image:    Array.isArray(prod.image) ? prod.image[0] : (prod.image || ''),
                rating:   prod.aggregateRating?.ratingValue || null,
                reviews:  prod.aggregateRating?.reviewCount || null,
                seller:   offer?.seller?.name || '',
            });
        }"""
        data = json.loads(page.evaluate(js))
        return Product(
            title=data.get('title') or '',
            price=parse_price(data['price']) if data.get('price') else None,
            url=url,
            source='noon',
            sku=data.get('sku', ''),
            brand=data.get('brand', ''),
            image=data.get('image', ''),
            raw=data,
        )


class AmazonAEScraper(PlaywrightScraper):
    slug = 'amazon-ae'
    search_wait_ms = 3_000

    def search_url(self, query: str) -> str:
        return f'https://www.amazon.ae/s?k={urllib.parse.quote_plus(query)}&i=aps'

    def parse_search(self, page: Page, limit: int) -> list[SearchResult]:
        js = """() => {
            const cards = [...document.querySelectorAll('[data-component-type="s-search-result"]')];
            return JSON.stringify(cards.map(c => {
                const asin = c.getAttribute('data-asin') || '';

                const h2Link = c.querySelector('h2 a');
                let title = (
                    h2Link?.getAttribute('aria-label') ||
                    c.querySelector('h2 a span.a-text-normal')?.innerText ||
                    c.querySelector('h2 .a-text-normal')?.innerText ||
                    ''
                ).trim();
                if (!title) {
                    const skipPhrases = ["you're seeing this ad", "sponsored ad"];
                    const spans = [...c.querySelectorAll('span, div')];
                    for (const el of spans) {
                        const t = (el.childNodes.length === 1 && el.firstChild.nodeType === 3)
                            ? el.innerText?.trim() : '';
                        if (t.length > 20 && t.length < 300 &&
                            !skipPhrases.some(p => t.toLowerCase().startsWith(p))) {
                            title = t;
                            break;
                        }
                    }
                }

                const priceEl = (
                    c.querySelector('.a-price[data-a-size="xl"] .a-offscreen') ||
                    c.querySelector('.a-price .a-offscreen')
                );
                const price = priceEl?.innerText?.trim() || '';

                let href = h2Link?.href || '';
                if (!href && asin) {
                    const dpLink = c.querySelector(`a[href*="/dp/${asin}"]`);
                    href = dpLink?.href || `https://www.amazon.ae/dp/${asin}`;
                }
                return {asin, title, price, href};
            }));
        }"""
        raw = json.loads(page.evaluate(js))
        results = []
        for r in raw:
            if not r.get('asin') or not r.get('title'):
                continue
            price_text = r.get('price', '')
            results.append(SearchResult(
                name=r['title'],
                price=parse_price(price_text) if price_text else None,
                sku=r['asin'],
                url=r.get('href') or f"https://www.amazon.ae/dp/{r['asin']}",
            ))
        return results

    def extract(self, page: Page, url: str) -> Product:
        with suppress(PWTimeout):
            page.wait_for_selector('#productTitle', timeout=8_000)
        js = r"""() => {
            const title = document.querySelector('#productTitle')?.innerText?.trim() || '';
            const price = (
                document.querySelector('.priceToPay .a-offscreen')?.innerText ||
                document.querySelector('#corePriceDisplay_desktop_feature_div .a-price .a-offscreen')?.innerText ||
                document.querySelector('#apex_offerDisplay_desktop .a-price .a-offscreen')?.innerText ||
                document.querySelector('#priceblock_ourprice')?.innerText ||
                document.querySelector('#priceblock_dealprice')?.innerText ||
                ''
            ).trim();
            const asin = document.querySelector('#ASIN')?.value || '';
            const rawBrand = document.querySelector('#bylineInfo')?.innerText?.trim() || '';
            const brand = rawBrand.replace(/^Visit the\s+/i, '').replace(/\s+Store\s*$/i, '').replace(/^Brand:\s*/i, '') || '';

            const specs = {};
            document.querySelectorAll('table tr').forEach(row => {
                const th = row.querySelector('th')?.innerText?.trim()?.replace(/\\s+/g, ' ').replace(/:$/, '') || '';
                const td = row.querySelector('td')?.innerText?.trim()?.replace(/\\s+/g, ' ') || '';
                if (th && td) specs[th] = td;
            });
            document.querySelectorAll('#detailBullets_feature_div li').forEach(li => {
                const spans = li.querySelectorAll('span.a-text-bold, span:not(.a-text-bold)');
                if (spans.length >= 2) {
                    const k = spans[0].innerText?.trim()?.replace(/\\s+/g, ' ').replace(/:$/, '') || '';
                    const v = spans[spans.length - 1].innerText?.trim()?.replace(/\\s+/g, ' ') || '';
                    if (k && v && k !== v) specs[k] = v;
                }
            });
            document.querySelectorAll('#productDetails_db_sections tr, #productDetails_techSpec_section_1 tr, #productDetails_techSpec_section_2 tr').forEach(row => {
                const th = row.querySelector('th')?.innerText?.trim()?.replace(/\\s+/g, ' ').replace(/:$/, '') || '';
                const td = row.querySelector('td')?.innerText?.trim()?.replace(/\\s+/g, ' ') || '';
                if (th && td) specs[th] = td;
            });
            const imgEl = (
                document.querySelector('#landingImage') ||
                document.querySelector('#imgTagWrapperId img') ||
                document.querySelector('#main-image')
            );
            const image = imgEl?.getAttribute('data-old-hires') || imgEl?.src || '';
            return JSON.stringify({title, price, asin, brand, specs, image});
        }"""
        data = json.loads(page.evaluate(js))
        return Product(
            title=data.get('title') or '',
            price=parse_price(data['price']) if data.get('price') else None,
            url=url,
            source='amazon',
            sku=data.get('asin', ''),
            brand=data.get('brand', ''),
            image=data.get('image', ''),
            raw=data,
        )


class IHerbAEScraper(PlaywrightScraper):
    slug = 'iherb-ae'
    search_ready = '.product-cell'
    search_wait_ms = 1_000

    def search_url(self, query: str) -> str:
        return f'https://ae.iherb.com/search?kw={urllib.parse.quote_plus(query)}'

    def parse_search(self, page: Page, limit: int) -> list[SearchResult]:
        js = r"""() => {
            const cards = [...document.querySelectorAll('.product-cell')];
            return JSON.stringify(cards.map(c => {
                const link  = c.querySelector('a.product-link, a[href*="/pr/"]');
                const href  = link?.href || '';
                const title = c.querySelector('.product-title')?.innerText?.trim() || '';
                const rawPrice = c.querySelector('.product-price')?.innerText?.trim() || '';
                const priceMatch = rawPrice.match(/AED\s*[\d,.]+/);
                const price = priceMatch ? priceMatch[0] : '';
                const prodId = c.getAttribute('data-product-id')
                    || href.match(/\/(\d+)(?:[/?#]|$)/)?.[1] || '';
                return {prodId, title, price, href};
            }));
        }"""
        raw = json.loads(page.evaluate(js))
        results = []
        for r in raw:
            if not r.get('prodId') or not r.get('title'):
                continue
            results.append(SearchResult(
                name=r['title'],
                price=parse_price(r['price']) if r.get('price') else None,
                sku=r['prodId'],
                url=r.get('href') or f"https://ae.iherb.com/pr/x/{r['prodId']}",
            ))
        return results

    def extract(self, page: Page, url: str) -> Product:
        with suppress(PWTimeout):
            page.wait_for_selector('script[type="application/ld+json"]', timeout=8_000)
        js = r"""() => {
            const lds = [...document.querySelectorAll('script[type="application/ld+json"]')]
                .map(s => { try { return JSON.parse(s.innerText); } catch { return null; } })
                .filter(Boolean);
            const prod = lds.find(l => l['@type'] === 'Product');
            if (!prod) return JSON.stringify({});
            const price = prod.offers?.price || null;
            const currency = prod.offers?.priceCurrency || 'AED';
            const weight = prod.weight ? `${prod.weight.value} ${prod.weight.unitText}` : null;

            let servingsPerContainer = '';
            const sfEl = document.querySelector(
                '#supplement-facts, .supplement-facts-v2, [class*="supplement-facts"], [id*="supplement-facts"]'
            );
            const sfText = sfEl ? sfEl.innerText : '';
            const sfMatch = sfText.match(/Servings?\s+Per\s+Container[:\s]+(\d+)/i);
            if (sfMatch) servingsPerContainer = sfMatch[1];

            const nutrition = {};
            let nutrition_per = '';
            const sfServSizeMatch = sfText.match(/Serving\s+Size[:\s]+([^\n]+)/i);
            let iherb_serving_units = 1;
            if (sfServSizeMatch) {
                nutrition_per = `per serving (${sfServSizeMatch[1].trim()})`;
                const unitMatch = sfServSizeMatch[1].trim().match(/^(\d+)/);
                if (unitMatch) iherb_serving_units = parseInt(unitMatch[1], 10);
            }
            if (sfEl) {
                sfEl.querySelectorAll('tr').forEach(row => {
                    const cells = row.querySelectorAll('td');
                    if (cells.length >= 2) {
                        const name = cells[0].innerText?.trim().replace(/\s+/g, ' ');
                        const val  = cells[1].innerText?.trim();
                        if (name && val && !/serving\s+size/i.test(name) && !/servings?\s+per/i.test(name)) {
                            nutrition[name] = val;
                        }
                    }
                });
                if (!Object.keys(nutrition).length) {
                    sfText.split('\n').forEach(line => {
                        const m = line.match(/^([A-Za-z][^*†‡\d]{2,}?)\s{2,}([\d.,]+\s*(?:mg|mcg|g|IU|%)?)\s*/);
                        if (m) nutrition[m[1].trim()] = m[2].trim();
                    });
                }
            }

            if (!servingsPerContainer && prod.name) {
                const countMatches = [...prod.name.matchAll(
                    /(\d+)\s*(?:fish gelatin\s+)?(?:veg(?:etable)?\s+)?(?:softgels?|capsules?|tablets?|gummies?|veg\s*caps?)/gi
                )];
                if (countMatches.length > 0) {
                    servingsPerContainer = countMatches[countMatches.length - 1][1];
                }
            }

            const variantGroups = {};
            try {
                const allProductLinks = [...document.querySelectorAll('a[href*="/pr/"]')];

                const containerMap = new Map();
                allProductLinks.forEach(a => {
                    const m = a.href?.match(/\/pr\/[^/?#]+\/(\d+)/);
                    if (!m) return;
                    let el = a.parentElement;
                    for (let i = 0; i < 5 && el; i++) {
                        const siblings = el.querySelectorAll(':scope a[href*="/pr/"]');
                        if (siblings.length >= 2) {
                            if (!containerMap.has(el)) containerMap.set(el, new Set());
                            containerMap.get(el).add(a);
                            break;
                        }
                        el = el.parentElement;
                    }
                });

                containerMap.forEach((linkSet, container) => {
                    if (linkSet.size < 2) return;

                    let groupLabel = '';
                    const candidates = [
                        container.previousElementSibling,
                        container.parentElement?.previousElementSibling,
                        container.parentElement?.firstElementChild,
                    ];
                    for (const cand of candidates) {
                        if (!cand || cand === container) continue;
                        const t = (cand.innerText || '').trim();
                        const m = t.match(/^([^:\n]{1,30}):/);
                        if (m) { groupLabel = m[1].trim(); break; }
                    }
                    if (!groupLabel) return;

                    const options = [];
                    linkSet.forEach(a => {
                        const idM = a.href?.match(/\/pr\/[^/?#]+\/(\d+)/);
                        if (!idM) return;
                        const prodId = idM[1];
                        const lines = (a.innerText || '').split('\n').map(l => l.trim()).filter(Boolean);
                        const label = lines.find(l => !/^AED/i.test(l)) || prodId;
                        const priceLine = lines.find(l => /AED/i.test(l)) || '';
                        const priceM = priceLine.match(/[\d.]+/);
                        const price = priceM ? parseFloat(priceM[0]) : null;
                        options.push({label, prodId, price});
                    });

                    if (options.length >= 2) variantGroups[groupLabel] = options;
                });
            } catch(e) {}

            const ldAvail = prod.offers?.availability || '';
            let stockStatus = ldAvail.includes('OutOfStock') ? 'out_of_stock'
                            : ldAvail.includes('InStock')   ? 'in_stock'
                            : '';
            let restockText = '';
            const bodyText = document.body?.innerText || '';
            const restockMatch = bodyText.match(/In stock ([A-Z][a-z]+ \d+)/);
            if (restockMatch) restockText = `In stock ${restockMatch[1]}`;
            else if (bodyText.includes('Get notified when this product becomes available'))
                restockText = 'Out of stock — notify available';

            return JSON.stringify({
                title:                prod.name || '',
                price:                price ? String(price) : '',
                sku:                  prod.sku || prod.mpn || prod.productID || '',
                productID:            prod.productID || '',
                brand:                prod.brand?.name || '',
                description:          prod.description || '',
                weight,
                currency,
                rating:               prod.aggregateRating?.ratingValue || null,
                reviews:              prod.aggregateRating?.reviewCount || null,
                image:                prod.image || '',
                availability:         ldAvail,
                stockStatus,
                restockText,
                servingsPerContainer,
                iherb_serving_units,
                variantGroups,
                nutrition,
                nutrition_per,
            });
        }"""
        data = json.loads(page.evaluate(js))
        svgs = data.get('servingsPerContainer')
        data['servings_per_item'] = int(svgs) if svgs else None
        data['iherb_serving_units'] = int(data.get('iherb_serving_units') or 1)
        data['stock_status'] = data.get('stockStatus', '')
        data['restock_text'] = data.get('restockText', '')
        data['variant_groups'] = data.get('variantGroups') or {}
        return Product(
            title=data.get('title') or '',
            price=float(data['price']) if data.get('price') else None,
            url=url,
            source='iherb',
            sku=data.get('productID') or data.get('sku') or '',
            brand=data.get('brand', ''),
            image=data.get('image', ''),
            raw=data,
        )


class CarrefourUAEScraper(PlaywrightScraper):
    slug = 'carrefour'
    stealth = True
    search_wait_ms = 5_000

    def search_url(self, query: str) -> str:
        return (
            f'https://www.carrefouruae.com/mafuae/en/search'
            f'?keyword={urllib.parse.quote_plus(query)}'
        )

    def parse_search(self, page: Page, limit: int) -> list[SearchResult]:
        js = r"""() => {
            const allLinks = [...document.querySelectorAll('a[href*="/p/"]')]
                .filter(a => /\/p\/\d/.test(a.href));

            const byPid = new Map();
            for (const a of allLinks) {
                const pid = a.href.split('?')[0].match(/\/p\/([^/?]+)/)?.[1] || '';
                if (!pid) continue;
                const text = a.innerText?.trim() || '';
                if (!byPid.has(pid)) {
                    byPid.set(pid, {a, text});
                } else if (!byPid.get(pid).text && text) {
                    byPid.set(pid, {a, text});
                }
            }

            return JSON.stringify([...byPid.entries()].map(([pid, {a, text}]) => {
                const href = a.href.split('?')[0];
                const title = text.substring(0, 120);

                let priceText = '';
                let el = a;
                for (let i = 0; i < 12; i++) {
                    el = el.parentElement;
                    if (!el) break;
                    const pd = [...el.querySelectorAll('div')].find(d => {
                        const t = d.innerText?.trim() || '';
                        return /\d+\s*\.\d+\s*AED/.test(t) && t.length < 25;
                    });
                    if (pd) {
                        const t = pd.innerText?.trim()?.replace(/\s+/g, '');
                        const m = t.match(/^([\d.]+)AED/);
                        priceText = m ? m[1] : '';
                        break;
                    }
                }
                return {href, pid, title, priceText};
            }).filter(r => r.pid && r.title));
        }"""
        raw = json.loads(page.evaluate(js))
        seen: set[str] = set()
        results = []
        for r in raw:
            if r['pid'] in seen:
                continue
            seen.add(r['pid'])
            results.append(SearchResult(
                name=r['title'],
                price=float(r['priceText']) if r.get('priceText') else None,
                sku=r['pid'],
                url=r['href'],
            ))
        return results

    def extract(self, page: Page, url: str) -> Product:
        with suppress(PWTimeout):
            page.wait_for_selector('h1', timeout=8_000)
        with suppress(PWTimeout):
            page.wait_for_selector('div.text-2xs', timeout=6_000)
        try:
            page.locator('button[data-testid="Nutrition Facts"]').click(timeout=3_000)
            try:
                page.wait_for_selector('div.divide-y', timeout=3_000)
            except PWTimeout:
                page.wait_for_timeout(1_000)
        except Exception:
            pass
        js = r"""() => {
            const lds = [...document.querySelectorAll('script[type="application/ld+json"]')]
                .map(s => { try { return JSON.parse(s.innerText); } catch { return null; } })
                .filter(Boolean);
            const prod = lds.find(l => l['@type'] === 'Product');

            const blob = [...document.querySelectorAll('script')]
                .map(s => s.textContent || '')
                .filter(t => t.includes('__next_f'))
                .join('');
            const fpMatch = blob.match(/\\?"finalPrice\\?"\s*:\s*\\?"?(\d+(?:\.\d+)?)/);
            const rscPrice = fpMatch ? fpMatch[1] : '';

            const offer = prod ? (Array.isArray(prod.offers) ? prod.offers[0] : prod.offers) : null;
            const ldPrice = (offer && offer.price != null && Number(offer.price) > 0)
                ? String(offer.price) : '';

            const priceRe = /\d+\s*\.\d+\s*AED/;
            const isPriceDiv = d => {
                const txt = d.innerText?.trim() || '';
                return priceRe.test(txt) && txt.length < 25;
            };
            let priceDiv = null;
            let node = document.querySelector('h1');
            for (let i = 0; node && i < 8 && !priceDiv; i++) {
                node = node.parentElement;
                if (node) priceDiv = [...node.querySelectorAll('div')].find(isPriceDiv);
            }
            if (!priceDiv) priceDiv = [...document.querySelectorAll('div')].find(isPriceDiv);
            let rawPrice = priceDiv?.innerText?.trim()?.replace(/\s+/g, '') || '';
            const priceMatch = rawPrice.match(/^([\d.]+)AED/);
            const domPrice = priceMatch ? priceMatch[1] : '';

            const nutrition = {};
            let nutrition_per = '';
            const divideY = document.querySelector('div.divide-y');
            if (divideY) {
                [...divideY.children].forEach(row => {
                    const nameEl = row.querySelector('span');
                    const valEl  = row.querySelector('[class*="font-bold"]');
                    const rawName = nameEl?.innerText?.trim() || '';
                    const val     = valEl?.innerText?.trim()  || '';
                    if (!rawName || !val) return;
                    if (/per\s*\d+|per\s*serving/i.test(val)) {
                        nutrition_per = val;
                        return;
                    }
                    const name = rawName
                        .replace(/\s*in\s*(kcal|kJ|mg|g|µg|IU)\s*$/i, ' ($1)')
                        .replace(/\s*Per\s*\d+\s*$/i, '')
                        .trim();
                    if (name) nutrition[name] = val;
                });
            }

            const ldImage = prod ? (Array.isArray(prod.image) ? prod.image[0] : (prod.image || '')) : '';
            const domImageEl = !ldImage && (
                document.querySelector('[data-testid="product-image"] img') ||
                document.querySelector('.product-image img') ||
                document.querySelector('img[alt][src*="carrefouruae"]')
            );
            const image = ldImage || domImageEl?.src || '';

            return JSON.stringify({
                title:    prod?.name || document.querySelector('h1')?.innerText?.trim() || '',
                sku:      prod?.sku || '',
                brand:    prod?.brand?.name || '',
                rscPrice,
                ldPrice,
                domPrice,
                image,
                nutrition,
                nutrition_per,
            });
        }"""
        data = json.loads(page.evaluate(js))
        price = data.get('rscPrice') or data.get('domPrice') or data.get('ldPrice')
        return Product(
            title=data.get('title') or '',
            price=float(price) if price else None,
            url=url,
            source='carrefour',
            sku=data.get('sku', ''),
            brand=data.get('brand', ''),
            image=data.get('image', ''),
            raw=data,
        )


class LuluUAEScraper(PlaywrightScraper):
    slug = 'lulu'
    stealth = True
    _BASE_URL = 'https://gcc.luluhypermarket.com'
    _HEADERS = {'User-Agent': USER_AGENT, 'Accept': 'application/json', 'Referer': _BASE_URL + '/'}

    def _get(self, path: str) -> dict:
        r = urllib.request.Request(self._BASE_URL + path, headers=self._HEADERS)
        with urllib.request.urlopen(r, timeout=12) as resp:
            return json.loads(resp.read())

    def search(self, query: str, limit: int) -> list[SearchResult]:
        try:
            data = self._get(
                f'/api/client/list/?search_text={urllib.parse.quote_plus(query)}'
                f'&page_size={limit}'
            )
        except Exception:
            return []

        results = []
        for p in data.get('products', [])[:limit]:
            pk = p.get('pk')
            name = p.get('name', '')
            sku = p.get('sku', str(pk))
            brand = p.get('attributes', {}).get('brand', '')

            price = None
            url_path = ''
            with suppress(Exception):
                pd = self._get(f'/api/client/product/{pk}/')
                prod_data = pd.get('product', {})
                price_str = str(prod_data.get('price') or '')
                price = float(price_str) if price_str else None
                url_path = prod_data.get('absolute_url', '')

            full_url = (
                f'{self._BASE_URL}/en-ae{url_path}'
                if url_path
                else f'{self._BASE_URL}/en-ae/x/p/{sku}/'
            )
            results.append(SearchResult(name=name, price=price, sku=sku, url=full_url, brand=brand))
        return results

    def product_url(self, sku: str) -> str:
        with suppress(Exception):
            data = self._get(f'/api/client/list/?search_text={sku}&page_size=5')
            for p in data.get('products', []):
                if str(p.get('sku')) == str(sku):
                    pk = p.get('pk')
                    if pk:
                        pd = self._get(f'/api/client/product/{pk}/')
                        abs_url = pd.get('product', {}).get('absolute_url', '')
                        if abs_url:
                            return f'{self._BASE_URL}/en-ae{abs_url}'
        return f'{self._BASE_URL}/en-ae/x/p/{sku}/'

    def extract(self, page: Page, url: str) -> Product:
        with suppress(PWTimeout):
            page.wait_for_selector('script[type="application/ld+json"]', timeout=8_000)
        js = r"""() => {
            const lds = [...document.querySelectorAll('script[type="application/ld+json"]')]
                .map(s => { try { return JSON.parse(s.innerText); } catch { return null; } })
                .filter(Boolean);
            const prod = lds.find(l => l['@type'] === 'Product');
            if (!prod) return JSON.stringify({});
            const offer = Array.isArray(prod.offers) ? prod.offers[0] : prod.offers;
            return JSON.stringify({
                title:        prod.name || '',
                price:        offer?.price != null ? String(offer.price) : '',
                sku:          prod.sku || '',
                brand:        prod.brand?.name || '',
                description:  prod.description || '',
                image:        Array.isArray(prod.image) ? prod.image[0] : (prod.image || ''),
                availability: offer?.availability || '',
            });
        }"""
        data = json.loads(page.evaluate(js))
        size_ml = parse_size_ml(f"{data.get('title', '')} {data.get('description', '')}")
        if size_ml:
            data['size_ml'] = size_ml
        return Product(
            title=data.get('title') or '',
            price=float(data['price']) if data.get('price') else None,
            url=url,
            source='lulu',
            sku=data.get('sku', ''),
            brand=data.get('brand', ''),
            image=data.get('image', ''),
            raw=data,
        )


class TalabatMartScraper(PlaywrightScraper):
    slug = 'talabat-mart'
    stealth = True
    _SKU_RE = re.compile(r'/s/(\d+)')

    def search(self, query: str, limit: int) -> list[SearchResult]:
        limit = min(limit, 10)
        q = urllib.parse.quote_plus(f'site:talabat.com/uae/talabat-mart/product {query}')
        search_url = f'https://www.google.com/search?q={q}&num={limit}&hl=en'
        with open_page(search_url, wait_for='domcontentloaded', stealth=True) as page:
            page.wait_for_timeout(2_000)
            js = r"""() => {
                const seen = new Set();
                const results = [];
                document.querySelectorAll('div.g, [class*="MjjYud"], [data-sokoban-container]')
                    .forEach(c => {
                        const a = c.querySelector('a[href*="talabat.com/uae/talabat-mart/product"]');
                        if (!a) return;
                        const url = a.href.split('?')[0].split('#')[0];
                        if (!url.includes('/s/') || seen.has(url)) return;
                        seen.add(url);
                        const title = c.querySelector('h3')?.innerText?.trim()
                                   || a.innerText?.trim() || '';
                        results.push({url, title});
                    });
                if (!results.length) {
                    document.querySelectorAll('a[href*="talabat.com/uae/talabat-mart/product"]')
                        .forEach(a => {
                            const url = a.href.split('?')[0].split('#')[0];
                            if (!url.includes('/s/') || seen.has(url)) return;
                            seen.add(url);
                            const ctx = a.closest('li, [class]');
                            const title = ctx?.querySelector('h3')?.innerText?.trim()
                                       || a.innerText?.trim() || '';
                            results.push({url, title});
                        });
                }
                return JSON.stringify(results);
            }"""
            raw = json.loads(page.evaluate(js))
        results = []
        for r in raw[:limit]:
            url = r.get('url', '')
            m = self._SKU_RE.search(url)
            if not m:
                continue
            sku = m.group(1)
            title = re.sub(r'\s*[-|]\s*[Tt]alabat.*$', '', r.get('title', '')).strip()
            if not title:
                slug = url.split('/product/')[-1].split('/s/')[0]
                title = slug.replace('-', ' ').title()
            results.append(SearchResult(name=title, price=None, sku=sku, url=url))
        return results

    def product_url(self, sku: str) -> str:
        if sku.startswith('http'):
            return sku
        return STORES.url('talabat-mart', sku)

    def extract(self, page: Page, url: str) -> Product:
        try:
            page.wait_for_selector('h1', timeout=8_000)
        except PWTimeout:
            pass
        page.wait_for_timeout(1_500)

        js = r"""() => {
            try {
                const nd = JSON.parse(document.getElementById('__NEXT_DATA__')?.textContent || 'null');
                if (nd) {
                    const pp = nd?.props?.pageProps;
                    const prod = pp?.product || pp?.productDetails || pp?.data?.product
                              || pp?.productData || pp?.initialData?.product;
                    if (prod && prod.name) {
                        return JSON.stringify({
                            title: prod.name || prod.title || '',
                            price: String(prod.priceAfterDiscount ?? prod.price ?? ''),
                            image: prod.image || prod.thumbnail || prod.imageUrl || '',
                            sku:   String(prod.sku || prod.id || ''),
                            _src:  '__next',
                        });
                    }
                }
            } catch(e) {}

            try {
                const lds = [...document.querySelectorAll('script[type="application/ld+json"]')]
                    .map(s => { try { return JSON.parse(s.textContent); } catch { return null; } })
                    .filter(Boolean).flat();
                const prod = lds.find(l => l['@type'] === 'Product');
                if (prod) {
                    const offersRaw = prod.offers;
                    const offer = Array.isArray(offersRaw) ? offersRaw[0] : offersRaw;
                    return JSON.stringify({
                        title: prod.name || '',
                        price: String(offer?.price ?? ''),
                        image: Array.isArray(prod.image) ? prod.image[0] : (prod.image || ''),
                        sku:   prod.sku || '',
                        _src:  'jsonld',
                    });
                }
            } catch(e) {}

            const title = document.querySelector('h1')?.innerText?.trim() || '';
            const priceEl = document.querySelector(
                '[data-testid*="price"], [class*="productPrice"], [class*="Price"] span'
            );
            const price = priceEl?.innerText?.replace(/[^0-9.]/g, '') || '';
            const img = document.querySelector(
                '[data-testid*="product"] img, [class*="product"] img, main img'
            )?.src || '';
            return JSON.stringify({title, price, image: img, sku: '', _src: 'dom'});
        }"""

        data = json.loads(page.evaluate(js))
        sku = data.get('sku') or ''
        if not sku:
            m = self._SKU_RE.search(page.url or url)
            sku = m.group(1) if m else ''
        return Product(
            title=data.get('title') or '',
            price=parse_price(str(data['price'])) if data.get('price') else None,
            url=page.url or url,
            source='talabat',
            sku=sku,
            image=data.get('image', ''),
            raw={**data, 'sku': sku},
        )


class NamshiScraper(PlaywrightScraper):
    slug = 'namshi'
    stealth = True
    search_wait_ms = 4_000

    def search_url(self, query: str) -> str:
        return f'https://www.namshi.com/uae-en/men/search/?q={urllib.parse.quote_plus(query)}'

    def parse_search(self, page: Page, limit: int) -> list[SearchResult]:
        js = r"""() => {
            const anchors = [...document.querySelectorAll('a[href*="/buy-"]')];
            return JSON.stringify(anchors.map(a => {
                const href = a.href;
                const skuMatch = href.match(/\/([A-Z0-9]{16,})\/p\//);
                const sku = skuMatch ? skuMatch[1] : '';

                const rawLines = (a.innerText || '').split('\n').map(l => l.trim()).filter(Boolean);

                const timerIdx = new Set();
                rawLines.forEach((l, i) => {
                    if (l === ':') {
                        if (i > 0 && /^\d{1,2}$/.test(rawLines[i-1])) timerIdx.add(i-1);
                        if (i < rawLines.length-1 && /^\d{1,2}$/.test(rawLines[i+1])) timerIdx.add(i+1);
                        timerIdx.add(i);
                    }
                });

                const lines = rawLines.filter((l, i) =>
                    !timerIdx.has(i) &&
                    !/^-\d+%$/.test(l) &&
                    l.length > 1 &&
                    l !== ''
                );

                const NOISE = new Set(['free delivery','selling out fast','lowest price of the year',
                    'new arrival','back in stock','20% back* | eoss','eoss']);
                const textLines = lines.filter(l => /[a-zA-Z]/.test(l) &&
                    !NOISE.has(l.toLowerCase()));
                const brand = textLines[0] || '';
                const name  = textLines[1] || '';

                const priceMatch = lines.find(l => /^\d[\d,]*$/.test(l));
                const price = priceMatch ? priceMatch.replace(/,/g, '') : '';

                return {sku, brand, name, price, href};
            }).filter(r => r.sku && r.name));
        }"""
        raw = json.loads(page.evaluate(js))
        seen: set[str] = set()
        results = []
        for r in raw:
            if r['sku'] in seen:
                continue
            seen.add(r['sku'])
            title = f"{r['brand']} {r['name']}".strip() if r.get('brand') else r['name']
            results.append(SearchResult(
                name=title,
                price=float(r['price']) if r.get('price') else None,
                sku=r['sku'],
                url=r['href'],
                brand=r.get('brand', ''),
            ))
        return results

    def extract(self, page: Page, url: str) -> Product:
        try:
            page.wait_for_selector('h1', timeout=8_000)
        except PWTimeout:
            pass
        page.evaluate('window.scrollTo(0, 600)')
        with suppress(PWTimeout):
            page.wait_for_selector('[class*="SizePills_sizePill"]', timeout=6_000)
        page.wait_for_timeout(1_500)
        js = r"""() => {
            const title = document.querySelector('h1')?.innerText?.trim() || '';
            const brandEl = document.querySelector('[class*="brand"], [class*="Brand"]');
            const brand = brandEl?.innerText?.trim() || '';
            const priceEls = [...document.querySelectorAll('[class*="price"], [class*="Price"]')];
            let price = '';
            for (const el of priceEls) {
                const txt = el.innerText?.trim() || '';
                const m = txt.match(/^[\d,]+(\.\d+)?/);
                if (m) { price = m[0].replace(/,/g, ''); break; }
            }
            const skuMatch = window.location.pathname.match(/\/([A-Z0-9]{16,})\/p\//);
            const sku = skuMatch ? skuMatch[1] : '';
            const imgEl = [...document.querySelectorAll('img.iiz__img, img[src*="nooncdn"]')]
                .find(i => i.src && !i.src.includes('.svg') && i.src.includes('nooncdn'));
            const image = imgEl?.src || '';
            const sizes = [...new Set(
                [...document.querySelectorAll('[class*="SizePills_sizePill"]')]
                    .filter(el => !el.className.includes('_oos_'))
                    .map(el => el.innerText?.trim() || '')
                    .filter(t => t && t.length <= 12)
            )];
            const bodyText = document.body?.innerText || '';
            const mm = bodyText.match(/Material Composition\s+([^\n]+)/i);
            const material = mm ? mm[1].trim() : '';
            return JSON.stringify({title, brand, price, sku, image, sizes, material});
        }"""
        data = json.loads(page.evaluate(js))
        return Product(
            title=data.get('title') or '',
            price=parse_price(data['price']) if data.get('price') else None,
            url=url,
            source='namshi',
            sku=data.get('sku', ''),
            brand=data.get('brand', ''),
            image=data.get('image', ''),
            raw=data,
        )


class OunassScraper(PlaywrightScraper):
    slug = 'ounass'
    search_wait_ms = 4_000

    def search_url(self, query: str) -> str:
        return (
            f'https://www.ounass.ae/men'
            f'?fh_location=/$s%3D{urllib.parse.quote_plus(query)}&searchType=direct'
        )

    def parse_search(self, page: Page, limit: int) -> list[SearchResult]:
        js = r"""() => {
            const anchors = [...document.querySelectorAll('a[href*="/shop-"]')];
            return JSON.stringify(anchors.map(a => {
                const href = a.href;
                const skuMatch = href.match(/-(\d{6,})_\d+\.html/);
                const sku = skuMatch ? skuMatch[1] : '';

                const lines = (a.innerText || '').split('\n')
                    .map(l => l.trim()).filter(l => l);
                let brand = '', name = '', price = '';
                for (const l of lines) {
                    if (!price) {
                        const pm = l.match(/^([\d,]+)\s*AED$/);
                        if (pm) { price = pm[1].replace(/,/g, ''); continue; }
                    }
                    if (!brand && l === l.toUpperCase() && /[A-Z]/.test(l) && l.length > 1
                        && !l.startsWith('+')) {
                        brand = l; continue;
                    }
                    if (!name && /[a-z]/.test(l)) { name = l; continue; }
                }
                return {sku, brand, name, price, href};
            }).filter(r => r.sku && r.name));
        }"""
        raw = json.loads(page.evaluate(js))
        seen: set[str] = set()
        results = []
        for r in raw:
            if r['sku'] in seen:
                continue
            seen.add(r['sku'])
            title = f"{r['brand']} {r['name']}".strip() if r.get('brand') else r['name']
            results.append(SearchResult(
                name=title,
                price=float(r['price']) if r.get('price') else None,
                sku=r['sku'],
                url=r['href'],
                brand=r.get('brand', ''),
            ))
        return results

    def extract(self, page: Page, url: str) -> Product:
        with suppress(PWTimeout):
            page.wait_for_selector('script[type="application/ld+json"]', timeout=8_000)
        js = r"""() => {
            const lds = [...document.querySelectorAll('script[type="application/ld+json"]')]
                .map(s => { try { return JSON.parse(s.innerText); } catch { return null; } })
                .filter(Boolean);
            const prod = lds.find(l => l['@type'] === 'Product' || l['@type'] === 'ProductGroup');
            if (!prod) return JSON.stringify({});
            const price = prod.offers?.price != null ? String(prod.offers.price) : '';
            return JSON.stringify({
                title:       prod.name || '',
                price,
                sku:         prod.sku || '',
                brand:       prod.brand?.name || '',
                description: prod.description || '',
                color:       prod.color || '',
                category:    prod.category || '',
                sizes:       prod.size || [],
                image:       Array.isArray(prod.image) ? prod.image[0] : (prod.image || ''),
            });
        }"""
        data = json.loads(page.evaluate(js))
        return Product(
            title=data.get('title') or '',
            price=float(data['price']) if data.get('price') else None,
            url=url,
            source='ounass',
            sku=data.get('sku', ''),
            brand=data.get('brand', ''),
            image=data.get('image', ''),
            raw=data,
        )


class SixthStreetScraper(PlaywrightScraper):
    slug = '6thstreet'
    search_wait_ms = 4_000

    def search_url(self, query: str) -> str:
        return (
            f'https://en-ae.6thstreet.com/catalogsearch/result/'
            f'?q={urllib.parse.quote_plus(query)}'
            f'&dFR%5Bin_stock%5D%5B0%5D=1&dFR%5Bgender%5D%5B0%5D=Men'
        )

    def parse_search(self, page: Page, limit: int) -> list[SearchResult]:
        js = r"""() => {
            const cards = [...document.querySelectorAll('li.ProductItem')];
            return JSON.stringify(cards.map(card => {
                const a = card.querySelector('a[href*="/buy-"]');
                if (!a) return null;
                const href = a.href.split('?')[0];

                const base = href.replace(/\.html$/, '').split('/').pop() || '';
                const parts = base.split('-');
                let sku = '';
                for (let i = parts.length - 1; i >= 0; i--) {
                    if (/^[a-z0-9]{6,}$/i.test(parts[i]) && /\d/.test(parts[i])) {
                        sku = parts[i]; break;
                    }
                }

                const BADGES = new Set(['new in','most viewed','best price','bestseller',
                    'debut discount','further reduction','sold out','few sizes left',
                    'back in stock','sale','outlet','eoss']);
                const lines = (card.innerText || '').split('\n')
                    .map(l => l.trim())
                    .filter(l => l && l.length > 1 && !/^[\xa0\s]+$/.test(l) &&
                        !BADGES.has(l.toLowerCase()) && !/^-\d+%$/.test(l));

                const textLines = lines.filter(l => /[a-zA-Z]/.test(l));
                const brand = textLines[0] || '';
                const name  = textLines[1] || '';

                const priceMatch = lines.find(l => /^\d[\d,]*$/.test(l));
                const price = priceMatch ? priceMatch.replace(/,/g, '') : '';

                return {sku, brand, name, price, href};
            }).filter(r => r && r.sku && r.name));
        }"""
        raw = json.loads(page.evaluate(js))
        seen: set[str] = set()
        results = []
        for r in raw:
            if r['sku'] in seen:
                continue
            seen.add(r['sku'])
            title = f"{r['brand']} {r['name']}".strip() if r.get('brand') else r['name']
            results.append(SearchResult(
                name=title,
                price=float(r['price']) if r.get('price') else None,
                sku=r['sku'],
                url=r['href'],
                brand=r.get('brand', ''),
            ))
        return results

    def _sku_from_url(self, url: str) -> str:
        base = re.sub(r'\.html$', '', url.split('?')[0].rstrip('/').split('/')[-1])
        parts = base.split('-')
        for part in reversed(parts):
            if re.match(r'^[a-z0-9]{6,}$', part, re.IGNORECASE) and re.search(r'\d', part):
                return part
        return parts[-1] if parts else ''

    def extract(self, page: Page, url: str) -> Product:
        with suppress(PWTimeout):
            page.wait_for_selector('script[type="application/ld+json"]', timeout=8_000)
        js = r"""() => {
            const lds = [...document.querySelectorAll('script[type="application/ld+json"]')]
                .map(s => { try { return JSON.parse(s.innerText); } catch { return null; } })
                .filter(Boolean)
                .flat();
            const prod = lds.find(l => l['@type'] === 'Product');
            if (!prod) return JSON.stringify({});
            const offersRaw = prod.offers;
            const offersList = Array.isArray(offersRaw) ? offersRaw : (offersRaw ? [offersRaw] : []);
            const price = offersList.length
                ? String(offersList[0].price ?? '')
                : (prod.offers?.price != null ? String(prod.offers.price) : '');
            const sizes = [...document.querySelectorAll('.sizeOptionLabel')]
                .filter(el => !el.closest('[class*="OOS"]'))
                .map(el => el.innerText?.trim())
                .filter(Boolean);
            return JSON.stringify({
                title:       prod.name || '',
                price,
                sku:         prod.sku || '',
                brand:       prod.brand?.name || '',
                description: prod.description || '',
                color:       prod.color || '',
                material:    prod.material || '',
                category:    prod.category || '',
                image:       Array.isArray(prod.image) ? prod.image[0] : (prod.image || ''),
                sizes,
            });
        }"""
        data = json.loads(page.evaluate(js))
        return Product(
            title=data.get('title') or '',
            price=parse_price(data['price']) if data.get('price') else None,
            url=url,
            source='sixthstreet',
            sku=data.get('sku', ''),
            brand=data.get('brand', ''),
            image=data.get('image', ''),
            raw=data,
        )


class NextScraper(PlaywrightScraper):
    slug = 'next'
    search_ready = '.MuiCardContent-root'
    search_wait_ms = 1_500
    product_wait_for = 'domcontentloaded'
    _CHROME_APP = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    _BROWSER = CdpBrowser(
        chrome_path=_CHROME_APP,
        profile_dir=Path.home() / '.cache' / 'personal-next-cdp',
        port=9222,
    )
    _LIMIT = RateLimiter(
        lock_path=Path.home() / '.cache' / 'personal-next.lock',
        min_interval=12.0,
        max_per_window=12,
        window_seconds=900.0,
    )
    block_retries = 4
    block_cooldown = 5.0

    _html = ''

    @contextmanager
    def _open_page(self, url: str, wait_for: str):
        self._LIMIT.wait()
        with self._BROWSER.page() as page:
            response = page.goto(url, wait_until=wait_for, timeout=45_000)
            status = response.status if response else 0
            self._html = response.text() if response else ''
            if status in (403, 429) or 'Access Denied' in self._html[:2000] or len(self._html) < 5_000:
                raise Blocked(f'next.ae blocked the request (HTTP {status}, {len(self._html)} bytes) for {url} — Akamai rate limit, wait for cooldown')
            self._simulate_human(page)
            yield page

    def _simulate_human(self, page: Page) -> None:
        with suppress(Exception):
            page.mouse.move(240, 320)
            page.mouse.move(680, 520, steps=8)
            page.mouse.wheel(0, 1400)
            page.wait_for_timeout(500)
            page.mouse.wheel(0, -500)

    def search_url(self, query: str) -> str:
        return f'https://www.next.ae/en/search?w={urllib.parse.quote_plus(query)}'

    def parse_search(self, page: Page, limit: int) -> list[SearchResult]:
        js = r"""() => {
            const cards = [...document.querySelectorAll('.MuiCardContent-root')];
            const seen = new Set();
            const out = [];
            for (const card of cards) {
                const a = card.querySelector('a[href*="/style/"]');
                if (!a) continue;
                const href = a.href.split('#')[0].split('?')[0];
                const m = href.match(/\/style\/[^/]+\/([A-Za-z0-9]+)/);
                if (!m || seen.has(m[1])) continue;
                seen.add(m[1]);
                const text = (card.innerText || '').replace(/\s+/g, ' ').trim();
                const priceMatch = text.match(/AED\s*([\d,]+)/);
                out.push({
                    sku: m[1],
                    name: text.split(/\s*AED/i)[0].trim(),
                    price: priceMatch ? priceMatch[1].replace(/,/g, '') : '',
                    href,
                });
            }
            return JSON.stringify(out);
        }"""
        raw = json.loads(page.evaluate(js))
        results = []
        for r in raw:
            if not r.get('name'):
                continue
            results.append(SearchResult(
                name=r['name'],
                price=float(r['price']) if r.get('price') else None,
                sku=r['sku'],
                url=r['href'],
            ))
        return results

    def extract(self, page: Page, url: str) -> Product:
        html = self._html
        records = []
        for block in re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.DOTALL):
            with suppress(json.JSONDecodeError):
                parsed = json.loads(block)
                records.extend(parsed if isinstance(parsed, list) else [parsed])
        records = [r for r in records if isinstance(r, dict)]
        group = next((r for r in records if r.get('@type') == 'ProductGroup'), {})
        variants = [r for r in records if r.get('@type') == 'Product']
        first = variants[0] if variants else group

        offer = {}
        sizes = {}
        for variant in variants:
            variant_offer = variant.get('offers') or {}
            if isinstance(variant_offer, list):
                variant_offer = variant_offer[0] if variant_offer else {}
            if not offer and variant_offer.get('price') is not None:
                offer = variant_offer
            if variant.get('size') and 'InStock' in variant_offer.get('availability', ''):
                sizes[variant['size']] = None
        sizes = list(sizes)

        image = group.get('image') or first.get('image') or ''
        data = {
            'title': group.get('name') or first.get('name') or '',
            'brand': (group.get('brand') or first.get('brand') or {}).get('name', ''),
            'image': image[0] if isinstance(image, list) else image,
            'color': first.get('color', ''),
            'material': first.get('material', ''),
            'description': first.get('description', ''),
            'sizes': sizes,
            'availability': offer.get('availability', ''),
        }
        price = offer.get('price')
        return Product(
            title=data['title'],
            price=float(price) if price else None,
            url=url,
            source='next',
            sku=self._sku_from_url(url),
            brand=data['brand'],
            image=data['image'],
            raw=data,
        )


SCRAPERS: dict[str, type[Scraper]] = {
    'talabat-mart': TalabatMartScraper,
    'amazon-ae':    AmazonAEScraper,
    'iherb-ae':     IHerbAEScraper,
    'noon-ae':      NoonUAEScraper,
    'noon-minutes': NoonMinutesScraper,
    'namshi':       NamshiScraper,
    'ounass':       OunassScraper,
    '6thstreet':    SixthStreetScraper,
    'carrefour':    CarrefourUAEScraper,
    'lulu':         LuluUAEScraper,
    'next':         NextScraper,
}
