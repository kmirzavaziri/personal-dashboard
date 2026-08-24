
from pathlib import Path

from health.nutrition import compute
from core.web.templating import make_env, trim_number
from core.item.nutrients import nutrient
from core.item.categories import food_categories
from pkg.model.io import read_yaml

HERE = Path(__file__).parent

_jinja = make_env(HERE)
_jinja.filters['nutrient_label'] = lambda k: nutrient(k).label
_jinja.filters['nutrient_unit'] = lambda k: nutrient(k).unit


def _fmt_actual(target) -> str:
    if target.actual is None:
        return '—'
    unit = nutrient(target.nutrient_key).unit
    sep = ' ' if unit and not unit.startswith('g') else ''
    return f'~{target.actual:.0f}{sep}{unit}'


def _tooltip_rows(target) -> list[dict]:
    if not target.contributors:
        return []
    unit = nutrient(target.nutrient_key).unit
    sep = ' ' if unit and not unit.startswith('g') else ''

    rows = []

    for cat in food_categories():
        group = [c for c in target.contributors if c.get('category') == cat.key]
        if not group:
            continue
        total_weekly = sum(c['value'] * c['servings_per_week'] for c in group)
        total_servings = sum(c['servings_per_week'] for c in group)
        daily_servings = total_servings / 7
        daily = total_weekly / 7
        avg = total_weekly / total_servings if total_servings else 0
        rows.append({
            'label': cat.label,
            'val': f'~{trim_number(daily_servings)}/day, ~{avg:.0f}{sep}{unit} avg',
            'daily': f'≈{daily:.0f}{sep}{unit}/day',
        })

    for c in target.contributors:
        if c.get('category') != 'supplement':
            continue
        daily_servings = c['servings_per_week'] / 7
        daily = c['value'] * daily_servings
        rows.append({
            'label': c['name'],
            'val': f'{c["value"]:.0f}{sep}{unit} × ~{trim_number(daily_servings)}/day',
            'daily': f'≈{daily:.0f}{sep}{unit}/day',
        })

    return rows


_jinja.filters['fmt_actual'] = _fmt_actual
_jinja.filters['tooltip_rows'] = _tooltip_rows


def render(services) -> str:
    config = services.config
    nutrition = compute(config)
    profile = read_yaml(config.health_db / 'profile.yaml')
    gym = read_yaml(config.health_db / 'gym.yaml')
    monitoring = read_yaml(config.health_db / 'monitoring.yaml') or []
    clinics = read_yaml(config.health_db / 'clinics.yaml') or {}
    skin_clinic = read_yaml(config.health_db / 'skin_clinic.yaml') or []

    template = _jinja.get_template('health.html')
    return template.render(
        context=profile['context'],
        goals=profile['goals'],
        care_guide=profile.get('care_guide', []),
        supplement_strategy=profile.get('supplement_strategy', []),
        nutrient_targets=nutrition.nutrient_targets,
        plan=nutrition.plan,
        pool=nutrition.pool,
        weekly_nutrition=nutrition.weekly_nutrition,
        batches=nutrition.batches,
        routine=nutrition.routine,
        batch_subtotals=nutrition.batch_subtotals,
        gym=gym,
        monitoring=monitoring,
        clinics=clinics,
        skin_clinic=skin_clinic,
    )
