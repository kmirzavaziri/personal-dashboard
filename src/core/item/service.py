import mimetypes
import re
import urllib.request

from core.item.item import Item
from core.store.registry import STORES
from core.store.source import Source


def resolve(key: str, kind: str | None = None) -> Item:
    item = Item.objects.get_or_none(key=key)
    if item is None or (kind is not None and item.kind != kind):
        raise ValueError(f'Item not found: {key}')
    return item


def _category(item: Item):
    if item.metadata.edible:
        return item.metadata.edible.category
    if item.metadata.clothing:
        return item.metadata.clothing.category
    return None


def listing(kind: str | None = None, category: str | None = None) -> list[dict]:
    out = []
    for item in sorted(Item.objects.all(), key=lambda i: i.key):
        if kind and item.kind != kind:
            continue
        cat = _category(item)
        if category and cat != category:
            continue
        out.append({'key': item.key, 'short_name': item.short_name, 'kind': item.kind,
                    'status': item.status, 'category': cat})
    return out


def create(key: str, data: dict) -> str:
    if Item.objects.get_or_none(key=key) is not None:
        raise ValueError(f'Item already exists: {key}')
    Item.model_validate({**data, 'key': key}).save()
    return f'Created {key}'


def get_field(key: str, field: str):
    item = resolve(key)
    if field not in type(item).model_fields:
        raise ValueError(f'Unknown field: {field}')
    return item.to_dict().get(field)


def delete(key: str) -> str:
    resolve(key).delete()
    return f'Removed {key}'


def download_image(config, key: str, url: str) -> str:
    images = config.images
    images.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as r:
        content_type = r.headers.get('Content-Type', 'image/jpeg').split(';')[0].strip()
        data = r.read()
    if not content_type.startswith('image/'):
        raise ValueError(f'Expected image content-type, got {content_type!r}')
    ext = mimetypes.guess_extension(content_type) or '.jpg'
    if ext in ('.jpe', '.jpeg'):
        ext = '.jpg'
    (images / f'{key}{ext}').write_bytes(data)
    return f'/storage/images/{key}{ext}'


def set_field(config, key: str, field: str, value, replace: bool = False) -> str:
    item = resolve(key)
    parts = field.split('.')
    if parts[0] not in type(item).model_fields:
        raise ValueError(f'Unknown field: {parts[0]}')
    if len(parts) == 1:
        summary = _apply_field(config, item, field, value, replace)
    else:
        parent = item
        for step in parts[:-1]:
            parent = getattr(parent, step, None)
            if parent is None:
                raise ValueError(f'{field}: "{step}" is not set on {key}')
        summary = _apply_nested(parent, parts[-1], value, replace)
    item.save()
    return f'{key}.{field} set' if summary == 'set' else f'{key}.{field}: {summary}'


def _apply_nested(parent, leaf: str, value, replace: bool) -> str:
    existing = getattr(parent, leaf)
    if not replace and isinstance(existing, dict) and isinstance(value, dict):
        setattr(parent, leaf, {**existing, **value})
        return f'merged {len(value)} key(s)'
    if not replace and isinstance(existing, list) and isinstance(value, list):
        additions = [v for v in value if v not in existing]
        setattr(parent, leaf, existing + additions)
        return f'appended {len(additions)} entr(ies) ({len(getattr(parent, leaf))} total)'
    setattr(parent, leaf, value)
    return 'set'


def _apply_field(config, item: Item, field: str, value, replace: bool) -> str:
    if field == 'image' and isinstance(value, str) and value.startswith('http'):
        item.image = download_image(config, item.key, value)
        return f'set ({item.image})'
    if field == 'search':
        incoming = value if isinstance(value, dict) else {}
        merged = incoming if replace else {**item.search.model_dump(exclude_defaults=True), **incoming}
        item.search = Item.Search.model_validate(merged)
        return f"set ({', '.join(merged) or 'empty'})"
    if field == 'sources':
        raw = value if isinstance(value, list) else [value]
        incoming = [Source.model_validate(e) for e in raw]
        if replace:
            item.sources = incoming
            return 'set'
        seen = {(s.store.slug, s.id) for s in item.sources}
        additions = [s for s in incoming if (s.store.slug, s.id) not in seen]
        item.sources = item.sources + additions
        return f'appended {len(additions)} entr(ies) ({len(item.sources)} total)'
    existing = getattr(item, field)
    if not replace and isinstance(existing, dict) and isinstance(value, dict):
        setattr(item, field, {**existing, **value})
        return f'merged {len(value)} key(s)'
    if not replace and isinstance(existing, list) and isinstance(value, list):
        additions = [v for v in value if v not in existing]
        setattr(item, field, existing + additions)
        return f'appended {len(additions)} entr(ies) ({len(getattr(item, field))} total)'
    setattr(item, field, value)
    return 'set'


def set_image(config, key: str, image_url: str) -> str:
    item = resolve(key)
    try:
        item.image = download_image(config, key, image_url)
        result = f'{key}: {item.image}'
    except Exception as exc:
        item.image = image_url
        result = f'{key}: download failed ({exc}), kept remote URL'
    item.save()
    return result


def sync_images(config) -> str:
    lines = []
    for item in sorted(Item.objects.filter(kind='edible'), key=lambda i: i.key):
        if not item.image or item.image.startswith('/storage/'):
            continue
        try:
            item.image = download_image(config, item.key, item.image)
            item.save()
            lines.append(f'  {item.key}: {item.image}')
        except Exception as exc:
            lines.append(f'  {item.key}: FAILED — {exc}')
    return '\n'.join(lines) or '(nothing to sync)'


def chosen_source(key: str, store: str | None = None) -> dict | None:
    item = resolve(key)
    if store:
        src = next((s for s in item.sources if s.store.slug == store), None)
    else:
        src = item.chosen_source
    if src is None:
        return None
    return {'store': src.store.slug, 'id': src.id, 'url': src.url or ''}


def _parse_serving_units(serving_size: str, category: str) -> int:
    if not serving_size or category != 'supplement':
        return 1
    m = re.match(r'(\d+)\s*(softgel|capsule|tablet|cap|pill|gummy|lozenge)', serving_size.strip(), re.IGNORECASE)
    return int(m.group(1)) if m else 1


def _derive_servings(store: str, item: Item, title: str, specs_servings, servings_per_item, iherb_serving_units) -> int | None:
    if specs_servings:
        return specs_servings
    servings = servings_per_item
    if servings is None and store in STORES.grocery_slugs():
        return 1
    if servings is None:
        hits = re.findall(
            r'(?<![A-Za-z0-9\-])(\d+)\s*(?:fish gelatin\s+)?(?:veg(?:etable)?\s+)?'
            r'(?:softgels?|capsules?|tablets?|gummies?|veg\s*caps?)',
            title or '', re.IGNORECASE,
        )
        if hits:
            servings = int(hits[-1])
    if servings is not None:
        edible = item.metadata.edible
        our_units = _parse_serving_units(edible.serving_size if edible else '', edible.category if edible else '')
        ratio = max(1, our_units // max(1, int(iherb_serving_units or 1)))
        if ratio > 1:
            try:
                servings = int(servings) // ratio
            except (TypeError, ValueError):
                pass
    return servings


def add_source(config, key: str, store: str, id: str, price=None, url=None, title='',
               out_of_stock: bool = False, size_ml=None, specs_servings=None,
               servings_per_item=None, iherb_serving_units=1) -> str:
    item = resolve(key)
    servings = _derive_servings(store, item, title, specs_servings, servings_per_item, iherb_serving_units)

    entry: dict = {'store': store, 'id': str(id)}
    if out_of_stock:
        entry['out_of_stock'] = True
    if price is not None:
        entry['price'] = price
    ml_per_serving = item.metadata.edible.ml_per_serving if item.metadata.edible else None
    if ml_per_serving and size_ml:
        entry['size_ml'] = size_ml
        servings = round(size_ml / ml_per_serving)
    elif servings is not None:
        try:
            entry['servings_per_item'] = int(servings)
        except (TypeError, ValueError):
            entry['servings_per_item'] = servings
    if url:
        entry['url'] = url

    item.sources = [s for s in item.sources if not (s.store.slug == store and s.id == str(id))]
    item.sources.append(Source.model_validate(entry))
    item.save()
    stock_label = ' [OUT OF STOCK]' if out_of_stock else ''
    return f'{key} [{store}]: saved{stock_label} — AED {price}, {servings} servings, url: {url or "—"}'
