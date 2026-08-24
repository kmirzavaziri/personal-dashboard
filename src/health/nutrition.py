import re
from dataclasses import dataclass

from pydantic import ConfigDict

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
)
from pkg.model.base import Model
from pkg.model.io import read_yaml

_WEEKEND  = {'Sat', 'Sun'}
_GYM_DAYS = {'Mon', 'Wed', 'Fri'}
_HOME_DAYS = _WEEKEND | _GYM_DAYS
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


def _infer_snack_location(day_name: str) -> str:
    return 'home' if day_name in _WEEKEND else 'office'


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


class DayPlan(Model):
    model_config = ConfigDict(extra='forbid', arbitrary_types_allowed=True)

    day: str
    breakfast_key: str
    lunch_key: str
    dinner_key: str
    snack_key: str
    night_snack_key: str
    nutrition: DayNutrition = DayNutrition(0, 0, 0)
    breakfast_location: str = ''
    snack_location: str = ''
    fish_conflict: bool = False
    breakfast_available: bool = True
    snack_available: bool = True
    night_available: bool = True


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
    plan: list[DayPlan]
    weekly_nutrition: DayNutrition
    batches: dict[str, Batch]
    routine: list[RoutinePhase]
    batch_subtotals: dict[str, int]


def _units_count(item: ScheduledItem) -> int:
    m = re.match(r'^(\d+)', str(item.metadata.edible.serving_size).strip())
    return int(m.group(1)) if m else 1


def _assign_day_locations(plan: list[DayPlan], pool: dict[str, ScheduledItem]) -> None:
    for day in plan:
        b_item = pool.get(day.breakfast_key)
        day.breakfast_location = _infer_breakfast_location(day.day, b_item) if b_item else 'home'
        day.snack_location = _infer_snack_location(day.day)


def _reachable_at_breakfast(item: ScheduledItem | None, location: str, day_name: str) -> bool:
    if item is None:
        return True
    locations = item.metadata.edible.locations
    if locations and location not in locations:
        return False
    return location != 'home' or day_name in _HOME_DAYS


def _reachable_at_home(item: ScheduledItem | None) -> bool:
    if item is None:
        return True
    locations = item.metadata.edible.locations
    return not locations or 'home' in locations


def _assign_availability(plan: list[DayPlan], pool: dict[str, ScheduledItem]) -> None:
    for day in plan:
        day.breakfast_available = _reachable_at_breakfast(
            pool.get(day.breakfast_key), day.breakfast_location, day.day)
        day.snack_available = _reachable_at_home(pool.get(day.snack_key))
        day.night_available = _reachable_at_home(pool.get(day.night_snack_key))


def _accumulate_macros(plan: list[DayPlan], pool: dict[str, ScheduledItem]) -> DayNutrition:
    total_protein = total_carbs = total_calories = 0.0
    for day in plan:
        p = c = k = 0.0
        for slot in PLAN_SLOTS:
            item = pool.get(getattr(day, slot))
            if not item:
                continue
            nutrition = item.metadata.edible.nutrition
            p += nutrition.get('protein_g', 0)
            c += nutrition.get('net_carbs_g', 0)
            k += nutrition.get('calories', 0)
        day.nutrition = DayNutrition(protein_g=p, net_carbs_g=c, calories=k)
        total_protein += p
        total_carbs += c
        total_calories += k
    return DayNutrition(protein_g=total_protein, net_carbs_g=total_carbs, calories=total_calories)


def _day_has_fish(day: DayPlan, pool: dict[str, ScheduledItem]) -> bool:
    for slot in ('breakfast_key', 'snack_key'):
        item = pool.get(getattr(day, slot, ''))
        if item and 'fish' in item.metadata.edible.has:
            return True
    return False


def _flag_fish_conflicts(plan: list[DayPlan], pool: dict[str, ScheduledItem]) -> None:
    for day in plan:
        if _day_has_fish(day, pool) and day.day not in _FISH_ALLOWED_DAYS:
            day.fish_conflict = True


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
    plan = DayPlan.from_file(config.health_db / 'weekly_plan.yaml')
    batches = load_batches(config)
    routine = load_routine(config)

    _assign_day_locations(plan, pool)
    _assign_availability(plan, pool)
    assign_scheduled_servings(pool, plan, batches)
    weekly_nutrition = _accumulate_macros(plan, pool)
    _flag_fish_conflicts(plan, pool)
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
