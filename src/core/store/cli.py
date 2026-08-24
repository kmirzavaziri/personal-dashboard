import json
import mimetypes
import re
import urllib.request
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path

import typer

from core.item.item import Item
from core.store.browser import fetch_page_text, search_food_image
from core.store.registry import STORES
from core.store.scrapers import SCRAPERS
from core.store.source import Source
from pkg.scraper.base import Blocked
from pkg.scraper.driver import Product

store_app = typer.Typer(no_args_is_help=True, add_completion=False, help='Query online stores and populate item sources')
images_app = typer.Typer(no_args_is_help=True, add_completion=False, help='Batch image operations')
store_app.add_typer(images_app, name='images')


def register(root: typer.Typer) -> None:
    root.add_typer(store_app, name='store')
    root.command(help='Fetch any URL with a real browser and print the page text.')(fetch)


def get_scraper(name: str):
    cls = SCRAPERS.get(name)
    if not cls:
        raise SystemExit(f"Unknown store '{name}'. Available: {', '.join(SCRAPERS)}")
    return cls()


def parse_fields(fields_str: str | None) -> set[str] | None:
    if not fields_str:
        return None
    return {f.strip() for f in fields_str.split(',')}


def compact_line(fields: set[str], parts: list[tuple[str, str]]) -> str:
    return '  ' + '  |  '.join(token for name, token in parts if name in fields and token)


def download_image_local(url: str, key: str, images_dir: Path) -> str:
    storage = images_dir
    storage.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as r:
        ct = r.headers.get('Content-Type', 'image/jpeg').split(';')[0].strip()
        data = r.read()
    if not ct.startswith('image/'):
        raise ValueError(f'Expected image content-type, got {ct!r}')
    ext = mimetypes.guess_extension(ct) or '.jpg'
    if ext in ('.jpe', '.jpeg'):
        ext = '.jpg'
    dest = storage / f'{key}{ext}'
    dest.write_bytes(data)
    return f'/storage/images/{key}{ext}'


def fetch(url: str = typer.Argument(..., help='URL to fetch with a real browser')):
    text, jsonld = fetch_page_text(url)
    print(text)
    if jsonld:
        print('\n--- JSON-LD ---')
        print(json.dumps(jsonld, indent=2, ensure_ascii=False))


@store_app.command(help='Search products on a store.')
def search(
    query: str,
    store: str = typer.Option('talabat-mart'),
    limit: int = typer.Option(20),
    json_out: bool = typer.Option(False, '--json'),
    fields: str = typer.Option(None, help='Comma-separated fields: name,price,id,url (compact output)'),
):
    scraper = get_scraper(store)
    try:
        results = scraper.search(query, limit=limit)
    except Blocked as exc:
        raise SystemExit(str(exc))
    if json_out:
        print(json.dumps([asdict(r) for r in results], indent=2))
        return
    if not results:
        print('No results.')
        return
    field_set = parse_fields(fields)
    if field_set:
        for r in results:
            url = ''
            if r.sku:
                with suppress(Exception):
                    url = scraper.product_url(r.sku)
            print(compact_line(field_set, [
                ('name',  r.name),
                ('price', f'AED {r.price}'),
                ('id',    f'id:{r.sku}' if r.sku else ''),
                ('url',   url),
            ]))
    else:
        print(f"\nResults from {store} — '{query}':\n")
        for r in results:
            print(f'  {r.name}')
            print(f'    AED {r.price}  sku:{r.sku}')
            url = r.url or (scraper.product_url(r.sku) if r.sku else '')
            if url:
                print(f'    {url}')
            print()


@store_app.command(name='product', help='Fetch a product by id.')
def product_cmd(
    id: str = typer.Argument(..., help='Product UUID / id'),
    store: str = typer.Option('talabat-mart'),
    json_out: bool = typer.Option(False, '--json'),
    fields: str = typer.Option(None, help='Comma-separated fields: name,price,id,servings,url'),
):
    scraper = get_scraper(store)
    try:
        p = scraper.get_product(id)
    except Blocked as exc:
        raise SystemExit(str(exc))
    if json_out:
        print(json.dumps(asdict(p), indent=2))
        return
    field_set = parse_fields(fields)
    raw = p.raw

    specs = raw.get('specs') or {}
    servings = (
        specs.get('Total Servings Per Container')
        or specs.get('Servings Per Container')
        or raw.get('servings_per_item')
    )

    if field_set:
        print(compact_line(field_set, [
            ('name',     p.title),
            ('price',    f'AED {p.price}'),
            ('id',       f'id:{p.sku}'),
            ('servings', f'{servings}srv' if servings else ''),
            ('size_ml',  f"{raw['size_ml']}ml" if raw.get('size_ml') else ''),
            ('stock',    raw.get('restock_text') or raw.get('stock_status') or '—'),
            ('url',      p.url or ''),
        ]))
    else:
        print(f'\nProduct: {p.title}')
        print(f'  Price   : AED {p.price}')
        print(f'  ID/SKU  : {p.sku}')
        if p.url:
            print(f'  URL     : {p.url}')
        if servings:
            print(f'  Servings: {servings}')
        stock = raw.get('stock_status', '')
        restock = raw.get('restock_text', '')
        if restock:
            print(f'  Stock   : {restock}')
        elif stock:
            print(f'  Stock   : {stock}')
        nut = raw.get('nutrition', {})
        if nut:
            per = raw.get('nutrition_per', '')
            label = f'Nutrition ({per})' if per else 'Nutrition'
            print(f'  {label}:')
            for k, v in nut.items():
                print(f'    {k}: {v}')


@store_app.command(help='Fetch an image for an item and save it to the item YAML.')
def image(
    ctx: typer.Context,
    key: str,
    store: str = typer.Option(None, help="Use this store's source instead of the chosen one"),
    search: str = typer.Option(None, metavar='QUERY', help='Fall back to Google Images with this query'),
):
    config = ctx.obj.config
    item = Item.objects.get_or_none(key=key)
    if not item:
        raise SystemExit(f'Item not found: {key}')
    if store:
        src = next((s for s in item.sources if s.store.slug == store), None)
        if not src:
            raise SystemExit(f'No {store} source for {key}')
    else:
        src = item.chosen_source
    if (item.image or '').startswith('/storage/'):
        print(f'  {key}: already has local image, skipping')
        return
    img = ''
    store_slug = 'unknown'
    if src:
        store_slug = src.store.slug
        product_id = str(src.url or src.id)
        scraper = None
        if product_id:
            try:
                scraper = get_scraper(store_slug)
            except SystemExit:
                scraper = None
        if product_id and scraper:
            p = scraper.get_product(product_id)
            img = p.image or p.raw.get('image', '')
        elif not product_id:
            print(f'  {key} [{store_slug}]: source has no id')
    else:
        if not search:
            raise SystemExit(f'No priced source for {key}')
    if not img and search:
        print(f"  {key}: no source image, searching Google Images for '{search}'...")
        img = search_food_image(search)
    if not img:
        print(f'  {key} [{store_slug}]: no image found')
        return
    try:
        local_path = download_image_local(img, key, config.images)
        item.image = local_path
        print(f'  {key} [{store_slug}]: {local_path}')
    except Exception as e:
        item.image = img
        print(f'  {key} [{store_slug}]: download failed ({e}), keeping remote URL')
    item.save()


@images_app.command(help='Download all remote image URLs to local storage.')
def sync(ctx: typer.Context):
    config = ctx.obj.config
    for item in sorted(Item.objects.filter(kind='edible'), key=lambda i: i.key):
        key = item.key
        img = item.image
        if not img or img.startswith('/storage/'):
            continue
        try:
            local_path = download_image_local(img, key, config.images)
            item.image = local_path
            item.save()
            print(f'  {key}: {local_path}')
        except Exception as e:
            print(f'  {key}: FAILED — {e}')


@store_app.command(help='Check or populate item sources across stores.')
def populate(
    ctx: typer.Context,
    key: str,
    store: str = typer.Option(None, help='Specific store key. Omit to check all stores.'),
    id: str = typer.Option(None, help='Product id — fetch and save this source'),
    query: str = typer.Option(None, help="Override search keyword (default: item's search.query)"),
):
    item = Item.objects.get_or_none(key=key)
    if item is None:
        raise SystemExit(f'Item not found: {key}')
    if store and id:
        _save_source(item, store, id)
    else:
        _check_stores(item, store, query)


def _parse_serving_units(serving_size: str, category: str) -> int:
    if not serving_size or category != 'supplement':
        return 1
    m = re.match(r'(\d+)\s*(softgel|capsule|tablet|cap|pill|gummy|lozenge)', serving_size.strip(), re.IGNORECASE)
    return int(m.group(1)) if m else 1


def _derive_servings(store_key: str, item, p: Product) -> int | None:
    raw = p.raw
    specs = raw.get('specs') or {}
    servings = specs.get('Total Servings Per Container') or specs.get('Servings Per Container')
    if servings:
        return servings

    servings = raw.get('servings_per_item')

    if servings is None and store_key in STORES.grocery_slugs():
        return 1

    if servings is None:
        hits = re.findall(
            r'(?<![A-Za-z0-9\-])(\d+)\s*(?:fish gelatin\s+)?(?:veg(?:etable)?\s+)?'
            r'(?:softgels?|capsules?|tablets?|gummies?|veg\s*caps?)',
            p.title, re.IGNORECASE,
        )
        if hits:
            servings = int(hits[-1])

    if servings is not None:
        edible = item.metadata.edible
        our_units = _parse_serving_units(edible.serving_size if edible else '', edible.category if edible else '')
        iherb_units = int(raw.get('iherb_serving_units') or 1)
        ratio = max(1, our_units // max(1, iherb_units))
        if ratio > 1:
            try:
                servings = int(servings) // ratio
            except (TypeError, ValueError):
                pass
    return servings


def _print_variants(key: str, store: str, id: str, p: Product) -> None:
    variant_groups = p.raw.get('variant_groups') or {}
    if not variant_groups:
        return
    current_id = str(id)
    print('\n  Variants found on this page:')
    other_ids = []
    for group_name, options in variant_groups.items():
        print(f'    {group_name}:')
        for opt in options:
            oid = str(opt.get('prodId', ''))
            label = opt.get('label', oid)
            opt_price = opt.get('price')
            price_str = f'  AED {opt_price}' if opt_price is not None else ''
            marker = '  ← current' if oid == current_id else ''
            print(f'      {label:<18}  id:{oid}{price_str}{marker}')
            if oid and oid != current_id:
                other_ids.append(oid)
    other_ids = list(dict.fromkeys(other_ids))
    if other_ids:
        print('\n  To save additional variants:')
        for oid in other_ids:
            print(f'    dash store populate {key} --store {store} --id {oid}')


def _save_source(item, store: str, id: str) -> None:
    scraper = get_scraper(store)
    p = scraper.get_product(id)

    is_out_of_stock = (p.raw.get('stock_status') or '') == 'out_of_stock'
    price = p.price
    servings = _derive_servings(store, item, p)

    entry = {'store': store, 'id': id}
    if is_out_of_stock:
        entry['out_of_stock'] = True
    if price is not None:
        entry['price'] = price
    ml_per_serving = item.metadata.edible.ml_per_serving if item.metadata.edible else None
    size_ml = p.raw.get('size_ml')
    if ml_per_serving and size_ml:
        entry['size_ml'] = size_ml
        servings = round(size_ml / ml_per_serving)
    elif servings is not None:
        try:
            entry['servings_per_item'] = int(servings)
        except (TypeError, ValueError):
            entry['servings_per_item'] = servings
    url = p.url or ''
    if url:
        entry['url'] = url

    item.sources = [s for s in item.sources
                    if not (s.store.slug == store and s.id == str(id))]
    item.sources.append(Source.model_validate(entry))
    item.save()

    stock_label = ' [OUT OF STOCK]' if is_out_of_stock else ''
    print(f"  {item.key} [{store}]: saved{stock_label} — AED {price}, {servings} servings, url: {url or '—'}")
    _print_variants(item.key, store, id, p)


def _check_stores(item, store: str, query: str) -> None:
    query = query or item.search.query
    if not query:
        raise SystemExit(f"Item '{item.key}' has no search.query — add one to the YAML first or pass --query")
    print(f'\n{item.key}  (query: "{query}")\n')

    stores_to_check = [store] if store else (item.search.sources or STORES.scrapeable_slugs())
    ml_per_serving = item.metadata.edible.ml_per_serving if item.metadata.edible else None

    def _srv(src: Source):
        s = src.servings_per_item
        if s is None and src.size_ml and ml_per_serving:
            s = round(src.size_ml / ml_per_serving)
        return s if s is not None else '?'

    sources_by_store: dict[str, list] = {}
    for s in item.sources:
        sources_by_store.setdefault(s.store.slug, []).append(s)

    for store_key in stores_to_check:
        if store_key in sources_by_store:
            entries = sources_by_store[store_key]
            if len(entries) == 1:
                print(f'  {store_key:<16} ✓  AED {entries[0].price} / {_srv(entries[0])} srv')
            else:
                print(f'  {store_key:<16} ✓  {len(entries)} source(s):')
                for src in entries:
                    print(f'      AED {src.price} / {_srv(src)} srv  id:{src.id}')
            continue
        try:
            scraper = get_scraper(store_key)
            found = scraper.search(query, limit=5)
            if not found:
                print(f'  {store_key:<16} —  no results')
            else:
                print(f'  {store_key:<16} ?  {len(found)} result(s):')
                for r in found:
                    print(f'      {r.name}  |  {r.sku}')
        except SystemExit:
            print(f'  {store_key:<16} —  store unavailable')
        except Exception as exc:
            print(f'  {store_key:<16} !  {exc}')
