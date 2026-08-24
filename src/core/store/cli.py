import json
from contextlib import suppress
from dataclasses import asdict

import typer

from core.mcp_client import MCPClient
from core.store.browser import fetch_page_text, search_food_image
from core.store.scrapers import SCRAPERS
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


@store_app.command(help='Fetch an image for an item (scrape locally) and persist it via MCP.')
def image(
    ctx: typer.Context,
    key: str,
    store: str = typer.Option(None, help="Use this store's source instead of the chosen one"),
    search: str = typer.Option(None, metavar='QUERY', help='Fall back to Google Images with this query'),
):
    client = MCPClient.from_config(ctx.obj.config)
    if (client.call('item_get', key=key, field='image') or '').startswith('/storage/'):
        print(f'  {key}: already has local image, skipping')
        return
    src = client.call_json('item_chosen_source', key=key, store=store)
    img = ''
    store_slug = (src or {}).get('store', 'unknown')
    if src and (src.get('url') or src.get('id')):
        p = get_scraper(store_slug).get_product(src.get('url') or src['id'])
        img = p.image or p.raw.get('image', '')
    if not img and search:
        print(f"  {key}: no source image, searching Google Images for '{search}'...")
        img = search_food_image(search)
    if not img:
        print(f'  {key} [{store_slug}]: no image found')
        return
    print('  ' + client.call('item_set_image', key=key, image_url=img))


@images_app.command(help='Download all remote edible image URLs to local storage (runs on the server).')
def sync(ctx: typer.Context):
    print(MCPClient.from_config(ctx.obj.config).call('sync_images'))


@store_app.command(help='Search stores for a query, or persist one scraped source (--store --id) via MCP.')
def populate(
    ctx: typer.Context,
    key: str,
    store: str = typer.Option(None, help='Specific store key.'),
    id: str = typer.Option(None, help='Product id — scrape and persist this source'),
    query: str = typer.Option(None, help='Search keyword (required without --id)'),
):
    if store and id:
        _save_source(ctx.obj.config, key, store, id)
    else:
        _search_stores(store, query)


def _save_source(config, key: str, store: str, id: str) -> None:
    p = get_scraper(store).get_product(id)
    raw = p.raw
    specs = raw.get('specs') or {}
    result = MCPClient.from_config(config).call(
        'item_add_source', key=key, store=store, id=str(id), price=p.price, url=p.url or '',
        title=p.title, out_of_stock=(raw.get('stock_status') == 'out_of_stock'),
        size_ml=raw.get('size_ml'),
        specs_servings=specs.get('Total Servings Per Container') or specs.get('Servings Per Container'),
        servings_per_item=raw.get('servings_per_item'),
        iherb_serving_units=int(raw.get('iherb_serving_units') or 1),
    )
    print('  ' + result)
    _print_variants(key, store, id, p)


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


def _search_stores(store: str, query: str) -> None:
    if not query:
        raise SystemExit('Provide --query (the local box has no item data to read a stored query from).')
    from core.store.registry import STORES
    stores_to_check = [store] if store else STORES.scrapeable_slugs()
    print(f'\nquery: "{query}"\n')
    for store_key in stores_to_check:
        try:
            found = get_scraper(store_key).search(query, limit=5)
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
