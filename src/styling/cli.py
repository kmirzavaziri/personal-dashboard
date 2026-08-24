import typer

from core.mcp_client import MCPClient
from core.store.cli import get_scraper
from pkg.scraper.base import Blocked

styling_app = typer.Typer(no_args_is_help=True, add_completion=False, help='Scrape styling candidates (persisted via MCP)')


def register(root: typer.Typer) -> None:
    root.add_typer(styling_app, name='styling')


@styling_app.command(help='Fetch a product and add it as a candidate styling item (persisted via MCP).')
def add(
    ctx: typer.Context,
    store: str = typer.Option(..., help='Store key, e.g. namshi, ounass, 6thstreet, amazon-ae'),
    url: str = typer.Option(..., help='Product URL to fetch'),
    category: str = typer.Option(..., help='Item category, e.g. topwear, trouser, shoes'),
    goal: str = typer.Option(None, help='Transient goal label the candidate is being sourced for'),
    no_size_check: bool = typer.Option(False, '--no-size-check', help='Skip the Large-in-stock check (numeric sizing)'),
):
    try:
        p = get_scraper(store).get_product(url)
    except Blocked as exc:
        raise SystemExit(str(exc))
    result = MCPClient.from_config(ctx.obj.config).call(
        'styling_add', store=store, url=url, category=category, goal=goal or '',
        sku=p.sku, title=p.title, price=p.price, image_url=p.image or p.raw.get('image', ''),
        brand=p.brand, sizes=p.raw.get('sizes') or [], no_size_check=no_size_check,
    )
    print('  ' + result)


@styling_app.command(help='Re-fetch sources and recompute size availability (defaults to items with unknown size).')
def recheck(
    ctx: typer.Context,
    key: str = typer.Argument(None, help='Item key. Omit to process all items with unknown size.'),
    all: bool = typer.Option(False, '--all', help='Recompute for every clothing item, not just unknown ones.'),
):
    client = MCPClient.from_config(ctx.obj.config)
    targets = client.call_json('styling_recheck_targets')
    if key:
        targets = [t for t in targets if t['key'] == key]
        if not targets:
            raise SystemExit(f'Styling item not found or has no scrapeable source: {key}')
    elif not all:
        targets = [t for t in targets if t.get('size_ok') is None]

    for t in targets:
        try:
            product = get_scraper(t['store']).get_product(t['url'])
        except Blocked as exc:
            raise SystemExit(f'  Stopped — {exc}')
        except Exception as exc:
            print(f'  {t["key"]:32} fetch failed — {exc}')
            continue
        sizes = product.raw.get('sizes') or []
        print('  ' + client.call('styling_recheck', key=t['key'], sizes=sizes))
