
from pathlib import Path

from core.item.schedule import build_pool
from core.web.templating import make_env
from expenses.reference import category_account, category_display, expense_accounts
from pkg.model.io import read_yaml

HERE = Path(__file__).parent

_DAYS_PER_MONTH = 365.25 / 12

_WORKDAYS_PER_MONTH = _DAYS_PER_MONTH * 5 / 7

_FREQ_TO_MONTHLY = {
    'daily':    _DAYS_PER_MONTH,
    'workday':  _WORKDAYS_PER_MONTH,
    'weekly':   _DAYS_PER_MONTH / 7,
    'biweekly': _DAYS_PER_MONTH / 14,
    'monthly':  1.0,
    'yearly':   1.0 / 12,
}


def _to_monthly(cost: float, frequency: str) -> float:
    return cost * _FREQ_TO_MONTHLY.get(frequency, 1.0)


def render(services) -> str:
    config = services.config
    pool = build_pool(config)

    accounts: dict[str, list[dict]] = {a.key: [] for a in expense_accounts()}

    for key, item in sorted(pool.items(), key=lambda kv: kv[1].short_name):
        if item.metadata.edible.track_only:
            continue
        ppm = item.price_per_month
        if ppm is None or item.servings_per_week == 0:
            continue
        category = item.metadata.edible.category
        account = category_account(category)
        if account is None:
            continue
        src = item.chosen_source
        accounts[account].append({
            'name':     item.short_name,
            'category': category_display(category),
            'store':    src.store.display if src else '',
            'url':      item.url or '',
            'image':    item.image or '',
            'monthly':  ppm,
            'daily':    ppm / _DAYS_PER_MONTH,
        })

    recurring_raw = read_yaml(config.expenses_db / 'recurring.yaml') or []
    for entry in recurring_raw:
        cost = entry.get('cost_aed', 0) or 0
        freq = entry.get('frequency', 'monthly')
        account = entry.get('account', 'other')
        if account not in accounts:
            accounts[account] = []
        monthly = _to_monthly(cost, freq)
        accounts[account].append({
            'name':      entry.get('name', ''),
            'category':  entry.get('category', ''),
            'store':     entry.get('store', ''),
            'url':       '',
            'image':     '',
            'monthly':   monthly,
            'daily':     monthly / _DAYS_PER_MONTH,
            'per_event': cost,
            'workday':   freq == 'workday',
        })

    def _aggregate_by_store_category(rows: list[dict]) -> list[dict]:
        totals: dict[tuple[str, str], float] = {}
        for r in rows:
            key = (r['store'], r['category'])
            totals[key] = totals.get(key, 0.0) + r['monthly']
        return [
            {'store': store, 'category': category, 'monthly': total}
            for (store, category), total in sorted(
                totals.items(), key=lambda kv: (kv[0][1], kv[0][0])
            )
        ]

    account_sections = []
    for account in expense_accounts():
        raw = accounts.get(account.key, [])
        if not raw:
            continue
        tracking = account.tracking
        if tracking == 'monthly':
            display_rows = _aggregate_by_store_category(raw)
        else:
            display_rows = raw
        account_sections.append({
            'name':        account.key,
            'tracking':    tracking,
            'rows':        display_rows,
            'total':       sum(r['monthly'] for r in raw),
            'daily_total': sum(r['daily']   for r in raw),
        })

    grand_total = sum(s['total'] for s in account_sections)
    grand_daily = sum(s['daily_total'] for s in account_sections)

    cat_totals: dict[str, float] = {}
    for rows in accounts.values():
        for r in rows:
            cat = r.get('category') or 'Other'
            cat_totals[cat] = cat_totals.get(cat, 0.0) + r['monthly']
    by_category = sorted(cat_totals.items(), key=lambda kv: -kv[1])

    env = make_env(HERE)
    env.filters['fmt']  = lambda v: f'{v:,.0f}'
    env.filters['fmt1'] = lambda v: f'{v:.1f}'

    tmpl = env.get_template('expenses.html')
    return tmpl.render(
        account_sections=account_sections,
        grand_total=grand_total,
        grand_daily=grand_daily,
        by_category=by_category,
    )
