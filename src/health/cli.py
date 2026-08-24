import json

import typer

from core.mcp_client import MCPClient

item_app = typer.Typer(no_args_is_help=True, add_completion=False, help='Read item data files (edits go through MCP)')

_SLOT_ORDER = [
    ('breakfast_key',   'Breakfast'),
    ('lunch_key',       'Lunch'),
    ('dinner_key',      'Dinner'),
    ('snack_key',       'Snack'),
    ('night_snack_key', 'Night'),
]


def register(root: typer.Typer) -> None:
    root.command(help='Print the health plan (text or JSON).')(report)
    root.add_typer(item_app, name='item')


def report(ctx: typer.Context, json_out: bool = typer.Option(False, '--json', help='Output as JSON for machine consumption')):
    from health.nutrition import compute
    data = compute(ctx.obj.config)
    if json_out:
        print(json.dumps(_report_to_dict(data), indent=2, ensure_ascii=False))
    else:
        _report_text(data)


@item_app.command(help='Print a single field from an item file (read via MCP).')
def get(ctx: typer.Context, key: str, field: str):
    print(MCPClient.from_config(ctx.obj.config).call('item_get', key=key, field=field))


def _report_to_dict(data) -> dict:
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


def _report_text(data) -> None:
    sep = '-' * 72

    print('\n=== Daily Plan ===')
    print(sep)
    for day in data.plan:
        b_item = data.pool.get(day.breakfast_key)
        b_str = f'{b_item.short_name} [{day.breakfast_location}]' if b_item else day.breakfast_key
        row = [f'{day.day:<4}  {b_str:<30}']
        for slot, label in _SLOT_ORDER[1:]:
            key = getattr(day, slot, '')
            if key and key in data.pool:
                row.append(data.pool[key].short_name)
        print('  ' + '  │  '.join(row))
    print()

    conflicts = [d for d in data.plan if d.fish_conflict]
    if conflicts:
        print('=== Warnings ===')
        print(sep)
        for d in conflicts:
            print(f'  ✗  {d.day}: fish scheduled on a non-allowed day (allowed: Sat, Sun, Tue, Thu)')
        print()

    print('=== Daily Nutrition ===')
    print(sep)
    for day in data.plan:
        n = day.nutrition
        print(f'  {day.day:<4}  protein {n.protein_g:>5.0f} g  '
              f'net carbs {n.net_carbs_g:>5.1f} g  calories {n.calories:>6.0f} kcal')
    print(sep)
    w = data.weekly_nutrition
    print(f"  {'WEEK':<4}  protein {w.protein_g:>5.0f} g  "
          f'net carbs {w.net_carbs_g:>5.1f} g  calories {w.calories:>6.0f} kcal')
    avg_p = w.protein_g / 7
    avg_c = w.net_carbs_g / 7
    avg_k = w.calories / 7
    print(f"  {'AVG':<4}  protein {avg_p:>5.0f} g  "
          f'net carbs {avg_c:>5.1f} g  calories {avg_k:>6.0f} kcal')
    print()

    print('=== Nutrient Targets ===')
    print(sep)
    for s in data.nutrient_targets:
        if s.actual is None:
            sym, actual_str = ' ', '—'
        elif s.on_target:
            sym = '✓'
            actual_str = f'~{s.actual:.0f}'
        else:
            sym = '✗'
            actual_str = f'~{s.actual:.0f}'
        print(f'  {sym} {s.nutrient:<32}  target: {s.daily_target:<18}  actual: {actual_str}')
    print()

    categories = [('snack', 'Snacks / Breakfast'), ('supplement', 'Supplements')]
    monthly_totals: dict[str, float] = {}
    grand_monthly = 0.0

    for cat_key, cat_label in categories:
        items_list = [i for i in data.pool.values() if i.metadata.edible.category == cat_key]
        if not items_list:
            continue
        print(f'=== {cat_label} ===')
        print(sep)
        for item in items_list:
            occasions = ', '.join(item.occasions) if item.occasions else '—'
            if item.metadata.edible.category == 'meal':
                price_str = f'AED {item.price:.0f}/occasion' if item.price else 'no price'
            else:
                price_str = f'AED {item.price_per_serving:.2f}/srv' if item.price_per_serving else 'no price'
            ppw = f'  AED {item.price_per_week:.2f}/wk' if item.price_per_week else ''
            ppm = f'  AED {item.price_per_month:.0f}/mo' if item.price_per_month else ''
            ppp = f'  ({item.price_per_protein_g:.2f}/g prot)' if item.price_per_protein_g else ''
            status = f'  [{item.status}]' if item.status else ''
            print(f'  {item.servings_per_week:>2}×  {item.short_name:<24}  {occasions:<28}  {price_str}{ppw}{ppm}{ppp}{status}')
        cat_total = sum(i.price_per_month for i in items_list if i.price_per_month)
        monthly_totals[cat_label] = cat_total
        grand_monthly += cat_total
        print(sep)
        print(f"  {'':>2}    {'':24}  {'':28}  Subtotal: AED {cat_total:.0f}/mo")
        print()

    print(sep)
    for label, val in monthly_totals.items():
        print(f'  {label:<32}  AED {val:>6.0f} / mo')
    print(sep)
    print(f"  {'GRAND TOTAL':<32}  AED {grand_monthly:>6.0f} / mo")
    print()
