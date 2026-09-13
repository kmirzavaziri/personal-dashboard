import re
from dataclasses import dataclass

from core.config import Config
from core.item.item import Item
from core.item.scheduled import ScheduledItem
from core.item.schedule import (
    Batch,
    PLAN_SLOTS,
    apply_default_servings,
    assign_scheduled_servings,
    iter_entries,
    load_batches,
    load_plan,
)
from pkg.model.base import Model
from pkg.model.io import read_yaml

_WEEKEND = {'Sat', 'Sun'}
_GYM_DAYS = {'Mon', 'Wed', 'Fri'}
_FISH_ALLOWED_DAYS = {'Sat', 'Sun', 'Tue', 'Thu'}


def _infer_breakfast_location(day_name: str, item: ScheduledItem) -> str:
    if day_name in _WEEKEND:
        return 'home'
    locations = item.metadata.edible.locations
    if 'commute' in locations:
        return 'commute'
    if day_name in _GYM_DAYS and 'after_gym' in locations:
        return 'after_gym'
    if 'office' in locations:
        return 'office'
    return 'home'


class NutrientTarget(Model):
    nutrient: str
    daily_target: str
    purpose: str
    nutrient_key: str = ''
    target_min: float | None = None
    target_max: float | None = None
    actual: float | None = None
    on_target: bool | None = None
    contributors: list = []


@dataclass
class DayNutrition:
    protein_g: float
    net_carbs_g: float
    calories: float


@dataclass
class PlanRow:
    days: list[str]
    slots: dict[str, list[ScheduledItem]]
    nutrition: DayNutrition
    breakfast_location: str
    fish_conflict: bool

    @property
    def days_label(self) -> str:
        return ', '.join(self.days)


@dataclass
class RoutineSection:
    heading: str
    batches: list[str]
    note_mode: str
    subtotal_unit: str | None


@dataclass
class RoutinePhase:
    name: str
    sections: list[RoutineSection]


def load_routine(config: Config) -> list[RoutinePhase]:
    raw = read_yaml(config.health_db / 'routine.yaml') or []
    return [
        RoutinePhase(
            name=phase['name'],
            sections=[
                RoutineSection(
                    heading=section['heading'],
                    batches=section.get('batches', []),
                    note_mode=section.get('note_mode', ''),
                    subtotal_unit=section.get('subtotal_unit'),
                )
                for section in phase.get('sections', [])
            ],
        )
        for phase in raw
    ]


@dataclass
class WeeklyData:
    pool: dict[str, ScheduledItem]
    nutrient_targets: list[NutrientTarget]
    plan: list[PlanRow]
    weekly_nutrition: DayNutrition
    batches: dict[str, Batch]
    routine: list[RoutinePhase]
    batch_subtotals: dict[str, int]


def _units_count(item: ScheduledItem) -> int:
    m = re.match(r'^(\d+)', str(item.metadata.edible.serving_size).strip())
    return int(m.group(1)) if m else 1


def _build_rows(plan_groups, pool: dict[str, ScheduledItem]) -> tuple[list[PlanRow], DayNutrition]:
    rows: list[PlanRow] = []
    total = DayNutrition(0.0, 0.0, 0.0)
    for group in plan_groups:
        slots: dict[str, list[ScheduledItem]] = {}
        p = c = k = 0.0
        for occasion in PLAN_SLOTS:
            items = [pool[key] for key in getattr(group.plan, occasion) if key in pool]
            slots[occasion] = items
            for item in items:
                nutrition = item.metadata.edible.nutrition
                p += nutrition.get('protein_g', 0) or 0
                c += nutrition.get('net_carbs_g', 0) or 0
                k += nutrition.get('calories', 0) or 0
        breakfast = slots.get('breakfast') or []
        location = _infer_breakfast_location(group.days[0], breakfast[0]) if breakfast else 'home'
        has_fish = any('fish' in it.metadata.edible.has for items in slots.values() for it in items)
        fish_conflict = has_fish and any(d not in _FISH_ALLOWED_DAYS for d in group.days)
        rows.append(PlanRow(
            days=list(group.days), slots=slots,
            nutrition=DayNutrition(p, c, k),
            breakfast_location=location, fish_conflict=fish_conflict,
        ))
        n = len(group.days)
        total.protein_g += p * n
        total.net_carbs_g += c * n
        total.calories += k * n
    return rows, total


def _nutrient_totals(pool: dict[str, ScheduledItem]) -> tuple[dict[str, float], dict[str, list]]:
    nutrient_totals: dict[str, float] = {}
    nutrient_contributors: dict[str, list] = {}
    for item in pool.values():
        if item.servings_per_week == 0:
            continue
        for nutrient_key, nutrient_value in item.metadata.edible.nutrition.items():
            if not nutrient_value:
                continue
            nutrient_totals[nutrient_key] = nutrient_totals.get(nutrient_key, 0) + float(nutrient_value) * item.servings_per_week
            nutrient_contributors.setdefault(nutrient_key, []).append({
                'name': item.short_name,
                'value': float(nutrient_value),
                'servings_per_week': item.servings_per_week,
                'category': item.metadata.edible.category,
            })
    daily_averages = {k: v / 7 for k, v in nutrient_totals.items()}
    return daily_averages, nutrient_contributors


def _assign_nutrient_targets(
    nutrient_targets: list[NutrientTarget],
    daily_averages: dict[str, float],
    nutrient_contributors: dict[str, list],
) -> None:
    for s in nutrient_targets:
        if not s.nutrient_key:
            continue
        s.actual = daily_averages.get(s.nutrient_key, 0.0)
        in_range = True
        if s.target_min is not None and s.actual < s.target_min:
            in_range = False
        if s.target_max is not None and s.actual > s.target_max:
            in_range = False
        s.on_target = in_range
        s.contributors = sorted(
            nutrient_contributors.get(s.nutrient_key, []),
            key=lambda c: -(c['value'] * c['servings_per_week']),
        )


def _compute_batch_subtotals(batches: dict[str, Batch], pool: dict[str, ScheduledItem]) -> dict[str, int]:
    subtotals: dict[str, int] = {}
    for batch_key, batch in batches.items():
        total = sum(
            _units_count(pool[e.pool_key]) * e.servings
            for e in iter_entries(batch)
            if e.pool_key in pool and e.weekly_uses is None
        )
        if total > 0:
            subtotals[batch_key] = total
    return subtotals


def compute(config: Config) -> WeeklyData:
    pool = {item.key: ScheduledItem(item, 0, []) for item in Item.objects.filter(kind='edible')}
    nutrient_targets = NutrientTarget.from_file(config.health_db / 'nutrient_targets.yaml')
    plan_groups = load_plan(config)
    batches = load_batches(config)
    routine = load_routine(config)

    assign_scheduled_servings(pool, plan_groups, batches)
    plan, weekly_nutrition = _build_rows(plan_groups, pool)
    daily_averages, contributors = _nutrient_totals(pool)
    _assign_nutrient_targets(nutrient_targets, daily_averages, contributors)
    apply_default_servings(pool)
    batch_subtotals = _compute_batch_subtotals(batches, pool)

    return WeeklyData(
        pool=pool,
        nutrient_targets=nutrient_targets,
        plan=plan,
        weekly_nutrition=weekly_nutrition,
        batches=batches,
        routine=routine,
        batch_subtotals=batch_subtotals,
    )
