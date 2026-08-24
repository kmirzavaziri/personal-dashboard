from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from core.item.item import Item
from core.item.scheduled import ScheduledItem
from pkg.model.base import Model
from pkg.model.io import read_yaml

PLAN_SLOTS: dict[str, str] = {
    'breakfast_key': 'breakfast',
    'lunch_key': 'lunch',
    'dinner_key': 'dinner',
    'snack_key': 'snack',
    'night_snack_key': 'night snack',
}

_OCCASION_ORDER = list(PLAN_SLOTS.values())


class PlanDay(Model):
    day: str
    breakfast_key: str
    lunch_key: str
    dinner_key: str
    snack_key: str
    night_snack_key: str


class BatchEntry(BaseModel):
    model_config = ConfigDict(extra='forbid')

    pool_key: str = ''
    servings: int = 1
    weekly_uses: int | None = None
    note: str = ''
    alternates: list['BatchEntry'] = []


@dataclass
class Variant:
    name: str
    days: str
    entries: list[BatchEntry]


@dataclass
class Batch:
    key: str
    entries: list[BatchEntry]
    variants: list[Variant]


def load_plan(config) -> list[PlanDay]:
    return PlanDay.from_file(config.health_db / 'weekly_plan.yaml')


def load_batches(config) -> dict[str, Batch]:
    raw = read_yaml(config.health_db / 'batches.yaml') or {}
    batches: dict[str, Batch] = {}
    for key, value in raw.items():
        if isinstance(value, dict) and 'variants' in value:
            variants = [
                Variant(
                    name=v['name'],
                    days=v.get('days', ''),
                    entries=[BatchEntry.model_validate(e) for e in v.get('entries', [])],
                )
                for v in value['variants']
            ]
            batches[key] = Batch(key=key, entries=[], variants=variants)
        else:
            batches[key] = Batch(
                key=key,
                entries=[BatchEntry.model_validate(e) for e in value],
                variants=[],
            )
    return batches


def iter_entries(batch: Batch):
    if batch.variants:
        for variant in batch.variants:
            yield from variant.entries
    else:
        yield from batch.entries


def assign_scheduled_servings(pool, plan, batches: dict[str, Batch]) -> None:
    occasions_seen: dict[str, set[str]] = {key: set() for key in pool}

    for day in plan:
        for slot, occasion in PLAN_SLOTS.items():
            key = getattr(day, slot)
            if key not in pool:
                continue
            pool[key].servings_per_week += 1
            occasions_seen[key].add(occasion)

    for batch in batches.values():
        for entry in iter_entries(batch):
            if entry.pool_key in pool:
                if entry.weekly_uses is not None:
                    pool[entry.pool_key].servings_per_week += entry.weekly_uses
                else:
                    pool[entry.pool_key].servings_per_week += entry.servings * 7
            for alt in entry.alternates:
                if alt.pool_key in pool and alt.weekly_uses is not None:
                    pool[alt.pool_key].servings_per_week += alt.weekly_uses

    for key, occ_set in occasions_seen.items():
        pool[key].occasions = sorted(
            occ_set, key=lambda o: _OCCASION_ORDER.index(o) if o in _OCCASION_ORDER else 99
        )


def apply_default_servings(pool) -> None:
    for item in pool.values():
        if item.servings_per_week == 0 and item.metadata.edible.default_weekly_uses > 0:
            item.servings_per_week = item.metadata.edible.default_weekly_uses


def build_pool(config) -> dict[str, ScheduledItem]:
    pool = {
        item.key: ScheduledItem(item, 0, [])
        for item in Item.objects.filter(kind='edible')
    }
    assign_scheduled_servings(pool, load_plan(config), load_batches(config))
    apply_default_servings(pool)
    return pool
