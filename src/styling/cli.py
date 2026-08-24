import re
from urllib.parse import urlparse

import typer

from core.item.item import Item
from core.item.sizing import Fit, size_available
from core.item.status import status_values
from core.store.cli import get_scraper
from core.store.registry import STORES
from core.store.source import Source
from pkg.model.base import DoesNotExist
from pkg.model.io import read_yaml
from pkg.scraper.base import Blocked
from pkg.scraper.driver import Product

styling_app = typer.Typer(no_args_is_help=True, add_completion=False, help='Manage styling items and candidates')

_STATUSES = status_values('clothing')


def register(root: typer.Typer) -> None:
    root.add_typer(styling_app, name='styling')


def _key_from(p: Product, url: str) -> str:
    sku = p.sku
    if sku:
        return re.sub(r'[^a-zA-Z0-9_-]', '_', str(sku))
    parts = [s for s in urlparse(url).path.rstrip('/').split('/') if s]
    last = parts[-1] if parts else 'item'
    name = parts[-2] if last == 'p' and len(parts) >= 2 else last.removesuffix('.html')
    return re.sub(r'[^a-zA-Z0-9_-]', '_', name)[:80]


@styling_app.command(help='Fetch a product and add it as a candidate styling item.')
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

    raw = p.raw
    sizes = raw.get('sizes') or []
    size_ok = None
    if not no_size_check:
        fit = Fit.from_profile(read_yaml(ctx.obj.config.styling_db / 'profile.yaml') or {})
        size_ok = size_available(category, sizes, fit)

    key = _key_from(p, url)
    with_key = _existing(key)
    if with_key is not None:
        print(f'  Already tracked: {key}')
        return

    item = Item(
        key=key,
        kind='clothing',
        short_name=p.title,
        name=p.title,
        image=p.image or raw.get('image', ''),
        status='unavailable' if size_ok is False else 'candidate',
        sources=[Source(
            store=STORES.resolve(store),
            price=p.price,
            url=url,
        )],
        metadata=Item.Metadata(clothing=Item.Clothing(
            brand=p.brand,
            category=category,
            size_ok=size_ok,
            goal=goal or '',
        )),
    )
    item.save()
    size_note = '' if size_ok is None else (' · L ✓' if size_ok else ' · L ✗')
    goal_note = f' for {goal}' if goal else ''
    print(f"  Added candidate{goal_note}: {item.metadata.clothing.brand} {item.name}  AED {item.price or '?'}{size_note}  [{key}]")


@styling_app.command(help='Re-fetch sources and recompute size availability (defaults to items with unknown size).')
def recheck(
    ctx: typer.Context,
    key: str = typer.Argument(None, help='Item key. Omit to process all items with unknown size.'),
    all: bool = typer.Option(False, '--all', help='Recompute for every clothing item, not just unknown ones.'),
):
    fit = Fit.from_profile(read_yaml(ctx.obj.config.styling_db / 'profile.yaml') or {})
    if key:
        item = _existing(key)
        if item is None:
            raise SystemExit(f'Styling item not found: {key}')
        items = [item]
    elif all:
        items = Item.objects.filter(kind='clothing')
    else:
        items = [i for i in Item.objects.filter(kind='clothing') if i.metadata.clothing.size_ok is None]

    badges = {True: 'size ✓', False: 'size ✗', None: 'size —'}
    for item in items:
        src = next((s for s in item.sources if STORES.resolve(s.store.slug).scrapeable and s.url), None)
        if src is None:
            continue
        try:
            product = get_scraper(src.store.slug).get_product(src.url)
        except Blocked as exc:
            raise SystemExit(f'  Stopped — {exc}')
        except Exception as exc:
            print(f'  {item.key:32} fetch failed — {exc}')
            continue
        sizes = product.raw.get('sizes') or []
        before = item.metadata.clothing.size_ok
        after = size_available(item.metadata.clothing.category, sizes, fit)
        item.metadata.clothing.size_ok = after
        if after is False:
            item.status = 'unavailable'
        elif after is True and item.status == 'unavailable':
            item.status = 'candidate'
        item.save()
        change = '' if before == after else f'  ({before} → {after})'
        print(f'  {item.key:32} {badges[after]}  ·  {len(sizes)} sizes{change}')


@styling_app.command(help='Set concern badges on a styling item (e.g. "not breathable", "100% linen"). Empty clears them.')
def flag(
    ctx: typer.Context,
    key: str = typer.Argument(..., help='Styling item key'),
    labels: str = typer.Argument(None, help='Comma-separated concern labels; omit to clear'),
):
    item = _existing(key)
    if item is None:
        raise SystemExit(f'Styling item not found: {key}')
    item.metadata.clothing.flags = [s.strip() for s in labels.split(',') if s.strip()] if labels else []
    item.save()
    shown = ', '.join(item.metadata.clothing.flags) or '(cleared)'
    print(f'  {key} flags: {shown}')


@styling_app.command(help='Move a styling item to another group (change its status).')
def move(
    ctx: typer.Context,
    key: str = typer.Argument(..., help='Styling item key'),
    status: str = typer.Argument(..., help=f"New status: {', '.join(_STATUSES)}"),
):
    if status not in _STATUSES:
        raise SystemExit(f"Unknown status '{status}'. Valid: {', '.join(_STATUSES)}")
    item = _existing(key)
    if item is None:
        raise SystemExit(f'Styling item not found: {key}')
    item.status = status
    item.save()
    print(f'  {key} → {status}')


def _existing(key: str) -> Item | None:
    try:
        return Item.objects.get(key=key, kind='clothing')
    except DoesNotExist:
        return None
