
from pathlib import Path

from core.item.item import Item
from core.item.categories import edible_categories
from core.item.schedule import PLAN_SLOTS, build_pool, load_plan
from core.item.sourcing import store_pref_rank
from core.web.templating import DIRHAM, make_env, trim_number
from core.item.nutrients import nutrient
from core.store.registry import STORES

HERE = Path(__file__).parent


def _fmt_price(value) -> str:
    if value is None:
        return '—'
    return DIRHAM + f'{value:.2f}'


def _fmt_store(url: str) -> str:
    return STORES.display_for_url(url)


def _fmt_freq(value) -> str:
    if value is None or value <= 0:
        return '—'
    if value >= 1:
        return f'{trim_number(value)} per month'
    return f'1 every {trim_number(1 / value)} months'


_jinja = make_env(HERE)
_jinja.filters['fmt_price'] = _fmt_price
_jinja.filters['fmt_store'] = _fmt_store
_jinja.filters['fmt_freq'] = _fmt_freq
_jinja.filters['nutrient_label'] = lambda k: nutrient(k).label
_jinja.filters['nutrient_unit'] = lambda k: nutrient(k).unit


def _build_refs(plan) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = {}
    for group in plan:
        days = ' · '.join(group.days)
        for slot in PLAN_SLOTS:
            for key in dict.fromkeys(getattr(group.plan, slot)):
                refs.setdefault(key, []).append(f'{days} · {slot}')
    return refs


def _store_sort_key(item) -> tuple:
    src = item.chosen_source
    store = src.store.slug if src else ''
    cost = item.price_per_month or item.price_per_serving or 0
    return (store_pref_rank(store), -cost)


def render(services) -> str:
    config = services.config
    pool = build_pool(config)
    sorted_pool = dict(sorted(
        ((k, v) for k, v in pool.items()
         if not v.metadata.edible.track_only and v.metadata.edible.category != 'meal'),
        key=lambda kv: _store_sort_key(kv[1]),
    ))
    refs = _build_refs(load_plan(config))
    gear = {item.key: item for item in Item.objects.filter(kind='durable')}
    template = _jinja.get_template('shopping.html')
    return template.render(
        pool=sorted_pool,
        refs=refs,
        gear=gear,
        categories=edible_categories(),
    )
