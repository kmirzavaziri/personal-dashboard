
import calendar
from datetime import datetime, timezone
from pathlib import Path

import transactions.service as tx_service
from core.item.schedule import build_pool
from core.web.templating import make_env
from expenses.reference import category_account, category_display, expense_accounts
from pkg.model.io import read_yaml

HERE = Path(__file__).parent

_USD_AED = 3.6725

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


def _tx_aed(tx: dict) -> float:
    amount = tx.get('amount') or 0
    return amount * _USD_AED if (tx.get('currency') or 'AED').upper() == 'USD' else amount


def _tx_category(tx: dict) -> str:
    return tx.get('category_override') or tx.get('category') or 'Unlabeled'


def _budget_status(budget: float, actual: float, fraction: float) -> tuple[str, float]:
    projected = actual / fraction if fraction else actual
    if budget <= 0:
        return 'none', projected
    if actual >= budget:
        return 'red', projected
    if projected > budget:
        return 'yellow', projected
    return 'green', projected


def _budget_actuals(config, cat_totals: dict[str, float], now: datetime) -> tuple[list[dict], list[dict]]:
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    fraction = now.day / days_in_month

    month_txns = tx_service.transactions(config)
    actual_by_cat: dict[str, float] = {}
    for tx in month_txns:
        cat = _tx_category(tx)
        actual_by_cat[cat] = actual_by_cat.get(cat, 0.0) + _tx_aed(tx)

    rows = []
    for cat in set(cat_totals) | set(actual_by_cat):
        budget = cat_totals.get(cat, 0.0)
        actual = actual_by_cat.get(cat, 0.0)
        status, projected = _budget_status(budget, actual, fraction)
        note = ''
        if status == 'red':
            note = f'over budget (AED {actual - budget:,.0f} above)'
        elif status == 'yellow':
            daily_rate = actual / now.day if now.day else 0
            exhaust_day = budget / daily_rate if daily_rate else 0
            if 0 < exhaust_day <= days_in_month:
                note = f'on pace to exhaust by {now.replace(day=max(1, min(days_in_month, round(exhaust_day)))):%b %-d} (projected AED {projected:,.0f})'
            else:
                note = f'projected AED {projected:,.0f}'
        rows.append({
            'category': cat,
            'budget': budget,
            'actual': actual,
            'pct': min(actual / budget * 100, 100) if budget > 0 else 0,
            'status': status,
            'note': note,
        })
    rows.sort(key=lambda r: ({'red': 0, 'yellow': 1, 'green': 2, 'none': 3}[r['status']], -r['actual']))

    cards: dict[str, list[dict]] = {}
    for tx in month_txns:
        cards.setdefault(tx.get('account') or 'Unknown', []).append(tx)
    card_sections = []
    for account, txs in sorted(cards.items()):
        recent = sorted(txs, key=lambda t: t.get('ts', ''), reverse=True)
        card_sections.append({
            'account': account,
            'total': sum(_tx_aed(t) for t in txs),
            'count': len(txs),
            'txns': [{
                'id': t.get('id', ''),
                'when': (t.get('ts') or '')[:16].replace('T', ' '),
                'venue': t.get('venue', ''),
                'amount': _tx_aed(t),
                'currency': (t.get('currency') or 'AED'),
                'orig_amount': t.get('amount'),
                'category': _tx_category(t),
                'type': t.get('type', ''),
            } for t in recent[:25]],
        })
    return rows, card_sections


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

    now = datetime.now(timezone.utc)
    budget_rows, card_sections = _budget_actuals(config, cat_totals, now)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    period_label = f'{now:%B %Y} · day {now.day}/{days_in_month}'
    categories = sorted(set(cat_totals) | set(tx_service.label_categories(config)))

    env = make_env(HERE)
    env.filters['fmt']  = lambda v: f'{v:,.0f}'
    env.filters['fmt1'] = lambda v: f'{v:.1f}'

    tmpl = env.get_template('expenses.html')
    return tmpl.render(
        account_sections=account_sections,
        grand_total=grand_total,
        grand_daily=grand_daily,
        by_category=by_category,
        budget_rows=budget_rows,
        card_sections=card_sections,
        period_label=period_label,
        categories=categories,
    )
