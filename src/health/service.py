from health.nutrition import compute
from core.item.schedule import PLAN_SLOTS


def report_dict(config) -> dict:
    data = compute(config)

    plan = []
    for row in data.plan:
        slots = {}
        for occasion in PLAN_SLOTS:
            items = row.slots.get(occasion) or []
            if not items:
                continue
            slots[occasion] = [{'key': it.key, 'name': it.short_name} for it in items]
        plan.append({
            'days': row.days,
            'days_label': row.days_label,
            'location': row.breakfast_location,
            'fish_conflict': row.fish_conflict,
            'slots': slots,
            'nutrition': {
                'protein_g':   round(row.nutrition.protein_g, 1),
                'net_carbs_g': round(row.nutrition.net_carbs_g, 1),
                'calories':    round(row.nutrition.calories),
            },
        })

    nutrient_targets = []
    for s in data.nutrient_targets:
        nutrient_targets.append({
            'nutrient':     s.nutrient,
            'daily_target': s.daily_target,
            'nutrient_key': s.nutrient_key,
            'actual':       round(s.actual, 2) if s.actual is not None else None,
            'on_target':    s.on_target,
            'contributors': [
                {'name': c['name'], 'value': c['value'], 'servings_per_week': c['servings_per_week']}
                for c in (s.contributors or [])
            ],
        })

    pool = {}
    for key, item in data.pool.items():
        pool[key] = {
            'name':              item.short_name,
            'category':          item.metadata.edible.category,
            'serving_size':      item.metadata.edible.serving_size,
            'servings_per_week': item.servings_per_week,
            'occasions':         item.occasions,
            'price_per_serving': round(item.price_per_serving, 2) if item.price_per_serving else None,
            'price_per_week':    round(item.price_per_week, 2) if item.price_per_week else None,
            'price_per_month':   round(item.price_per_month, 2) if item.price_per_month else None,
            'status':            item.status,
        }

    return {
        'plan': plan,
        'weekly_nutrition': {
            'protein_g':   round(data.weekly_nutrition.protein_g, 1),
            'net_carbs_g': round(data.weekly_nutrition.net_carbs_g, 1),
            'calories':    round(data.weekly_nutrition.calories),
        },
        'nutrient_targets': nutrient_targets,
        'pool': pool,
    }
