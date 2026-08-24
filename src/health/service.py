from health.nutrition import compute

_SLOT_ORDER = [
    ('breakfast_key',   'Breakfast'),
    ('lunch_key',       'Lunch'),
    ('dinner_key',      'Dinner'),
    ('snack_key',       'Snack'),
    ('night_snack_key', 'Night'),
]


def report_dict(config) -> dict:
    data = compute(config)

    plan = []
    for day in data.plan:
        slots = {}
        for slot, label in _SLOT_ORDER:
            key = getattr(day, slot, '')
            if not key:
                continue
            item = data.pool.get(key)
            entry = {'key': key, 'name': item.short_name if item else key}
            if slot == 'breakfast_key':
                entry['location'] = day.breakfast_location
            slots[label] = entry
        plan.append({
            'day': day.day,
            'slots': slots,
            'nutrition': {
                'protein_g':   round(day.nutrition.protein_g, 1),
                'net_carbs_g': round(day.nutrition.net_carbs_g, 1),
                'calories':    round(day.nutrition.calories),
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
