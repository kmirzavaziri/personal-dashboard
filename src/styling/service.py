import re
from urllib.parse import urlparse

from core.item.item import Item
from core.item.sizing import Fit, size_available
from core.item.status import status_values
from core.store.registry import STORES
from core.store.source import Source
from pkg.model.io import read_yaml

STATUSES = status_values('clothing')


def _fit(config) -> Fit:
    return Fit.from_profile(read_yaml(config.styling_db / 'profile.yaml') or {})


def _key_from(sku: str | None, url: str) -> str:
    if sku:
        return re.sub(r'[^a-zA-Z0-9_-]', '_', str(sku))
    parts = [s for s in urlparse(url).path.rstrip('/').split('/') if s]
    last = parts[-1] if parts else 'item'
    name = parts[-2] if last == 'p' and len(parts) >= 2 else last.removesuffix('.html')
    return re.sub(r'[^a-zA-Z0-9_-]', '_', name)[:80]


def get(key: str) -> Item:
    item = Item.objects.get_or_none(key=key)
    if item is None or item.kind != 'clothing':
        raise ValueError(f'Styling item not found: {key}')
    return item


def add(config, store: str, url: str, category: str, goal: str = '', sku: str | None = None,
        title: str = '', price=None, image_url: str = '', brand: str = '',
        sizes=None, no_size_check: bool = False) -> str:
    size_ok = None
    if not no_size_check:
        size_ok = size_available(category, sizes or [], _fit(config))

    key = _key_from(sku, url)
    if Item.objects.get_or_none(key=key) is not None:
        return f'Already tracked: {key}'

    item = Item(
        key=key,
        kind='clothing',
        short_name=title,
        name=title,
        image=image_url,
        status='unavailable' if size_ok is False else 'candidate',
        sources=[Source(store=STORES.resolve(store), price=price, url=url)],
        metadata=Item.Metadata(clothing=Item.Clothing(
            brand=brand, category=category, size_ok=size_ok, goal=goal or '')),
    )
    item.save()
    size_note = '' if size_ok is None else (' · L ✓' if size_ok else ' · L ✗')
    return f'Added candidate: {brand} {title}  AED {price or "?"}{size_note}  [{key}]'


def recheck_targets() -> list[dict]:
    targets = []
    for item in Item.objects.filter(kind='clothing'):
        src = next((s for s in item.sources if STORES.resolve(s.store.slug).scrapeable and s.url), None)
        if src is not None:
            targets.append({'key': item.key, 'store': src.store.slug, 'url': src.url,
                            'size_ok': item.metadata.clothing.size_ok})
    return targets


def recheck(config, key: str, sizes) -> str:
    item = get(key)
    before = item.metadata.clothing.size_ok
    after = size_available(item.metadata.clothing.category, sizes or [], _fit(config))
    item.metadata.clothing.size_ok = after
    if after is False:
        item.status = 'unavailable'
    elif after is True and item.status == 'unavailable':
        item.status = 'candidate'
    item.save()
    badge = {True: 'size ✓', False: 'size ✗', None: 'size —'}[after]
    change = '' if before == after else f'  ({before} → {after})'
    return f'{key} {badge}  ·  {len(sizes or [])} sizes{change}'


def flag(key: str, labels) -> str:
    item = get(key)
    if isinstance(labels, str):
        labels = [s.strip() for s in labels.split(',') if s.strip()]
    item.metadata.clothing.flags = list(labels or [])
    item.save()
    return f'{key} flags: {", ".join(item.metadata.clothing.flags) or "(cleared)"}'


def move(key: str, status: str) -> str:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    item = get(key)
    item.status = status
    item.save()
    return f'{key} → {status}'
