
from pathlib import Path
from collections import defaultdict

from core.item.item import Item
from core.item.categories import clothing_section_of, clothing_sections
from core.web.templating import make_env
from pkg.model.io import read_yaml

HERE = Path(__file__).parent

_jinja = make_env(HERE)

_BRAND_PALETTE = (
    '#e06c75', '#61afef', '#98c379', '#e5c07b', '#c678dd', '#56b6c2',
    '#d19a66', '#e39ec1', '#7fd18e', '#b0a0f0', '#f0955e', '#5fb3d6',
)


def _brand_colors(items: list) -> dict[str, str]:
    brands = sorted({i.metadata.clothing.brand for i in items if i.metadata.clothing.brand})
    return {brand: _BRAND_PALETTE[index % len(_BRAND_PALETTE)] for index, brand in enumerate(brands)}


def _load_data() -> tuple[dict, dict, dict, dict, dict, dict]:
    sections: dict[str, list] = defaultdict(list)
    candidates: dict[str, list] = defaultdict(list)
    out_of_size: dict[str, list] = defaultdict(list)
    deferred: dict[str, list] = defaultdict(list)
    next_batch: dict[str, list] = defaultdict(list)
    owned: dict[str, list] = defaultdict(list)
    status_bucket = {
        'candidate': candidates, 'deferred': deferred, 'next_batch': next_batch,
        'unavailable': out_of_size, 'owned': owned, 'ordered': owned,
    }
    for item in Item.objects.filter(kind='clothing'):
        section_key = clothing_section_of(item.metadata.clothing.category.lower())
        status_bucket.get(item.status, sections)[section_key].append(item)
    for grouped in (candidates, out_of_size, deferred, next_batch, owned):
        for section_items in grouped.values():
            section_items.sort(key=lambda i: (i.metadata.clothing.brand or '').lower())
    return dict(sections), dict(candidates), dict(out_of_size), dict(deferred), dict(next_batch), dict(owned)


def _by_type(sections: dict) -> list[tuple[str, list]]:
    return [(s.label, sections[s.key]) for s in clothing_sections() if sections.get(s.key)]


def _by_store(sections: dict) -> list[tuple[str, list]]:
    store_groups: dict[str, list] = defaultdict(list)
    for section_items in sections.values():
        for item in section_items:
            store_groups[item.store_display or '—'].append(item)
    for items in store_groups.values():
        items.sort(key=lambda i: (i.metadata.clothing.category, (i.metadata.clothing.brand or '').lower()))
    return sorted(store_groups.items())


def _bucket_total(bucket: dict) -> int:
    return int(sum(i.price for section_items in bucket.values() for i in section_items if i.price))


def render(services) -> str:
    sections, candidates, out_of_size, deferred, next_batch, owned = _load_data()
    profile = read_yaml(services.config.styling_db / 'profile.yaml') or {}
    decided = [item for section_items in sections.values() for item in section_items]
    decided_pending = int(sum(i.price for i in decided if i.status == 'pending' and i.price))
    decided_basket = int(sum(i.price for i in decided if i.status == 'basket' and i.price))
    template = _jinja.get_template('review.html')
    return template.render(
        decided_by_type=_by_type(sections),
        decided_by_store=_by_store(sections),
        decided_pending=decided_pending,
        decided_basket=decided_basket,
        candidates=candidates,
        out_of_size=out_of_size,
        deferred=deferred,
        next_batch=next_batch,
        next_batch_total=_bucket_total(next_batch),
        owned=owned,
        section_order=clothing_sections(),
        brand_colors=_brand_colors(Item.objects.filter(kind='clothing')),
        context=profile.get('context', []),
        goals=profile.get('goals', []),
    )
