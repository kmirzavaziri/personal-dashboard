
from datetime import datetime, timedelta, timezone
from pathlib import Path

import transactions.service as tx_service
from transactions.ledger import Ledger
from core.item.schedule import build_pool
from core.labels import colors_for
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


def _budget_status(budget: float, actual: float, fraction: float) -> tuple[str, float]:
    projected = actual / fraction if fraction else actual
    if budget <= 0:
        return 'none', projected
    if actual >= budget:
        return 'red', projected
    if projected > budget:
        return 'yellow', projected
    return 'green', projected


def _budget_rows(entries, cat_totals: dict[str, float], period) -> list[dict]:
    actual_by_cat: dict[str, float] = {}
    for entry in entries:
        if entry.spend:
            name = entry.category_name or 'Uncategorized'
            actual_by_cat[name] = actual_by_cat.get(name, 0.0) + entry.tx.aed

    rows = []
    for cat in set(cat_totals) | set(actual_by_cat):
        budget = cat_totals.get(cat, 0.0)
        actual = actual_by_cat.get(cat, 0.0)
        status, projected = _budget_status(budget, actual, period.fraction)
        note = ''
        if status == 'red':
            note = f'{actual - budget:,.0f} over'
        elif status == 'yellow':
            daily_rate = actual / period.elapsed_days
            exhaust_day = budget / daily_rate if daily_rate else 0
            if 0 < exhaust_day <= period.length_days:
                note = f'runs out {period.day(max(1, round(exhaust_day))):%b %-d} · projected {projected:,.0f}'
            else:
                note = f'projected {projected:,.0f}'
        rows.append({
            'category': cat,
            'budget': budget,
            'actual': actual,
            'pct': min(actual / budget * 100, 100) if budget > 0 else 0,
            'status': status,
            'note': note,
        })
    rows.sort(key=lambda r: ({'red': 0, 'yellow': 1, 'green': 2, 'none': 3}[r['status']], -r['actual']))
    return rows


def _card_sections(config, entries) -> list[dict]:
    cards: dict[str, list] = {name: [] for name in tx_service.account_names(config)}
    for entry in entries:
        cards.setdefault(entry.account or 'Unknown', []).append(entry)
    return [{
        'account': account,
        'total': sum(e.tx.aed for e in entries if e.spend),
        'count': len(entries),
        'entries': sorted(entries, key=lambda e: e.tx.ts, reverse=True),
    } for account, entries in cards.items()]


def _category_cards(ledger, entries, averages: dict[str, float], rule_averages: dict) -> list[dict]:
    hits = ledger.rule_hits()
    period_totals: dict[str, float] = {}
    for entry in entries:
        if entry.category and entry.spend:
            period_totals[entry.category.key] = period_totals.get(entry.category.key, 0.0) + entry.tx.aed
    return [{
        'category': category,
        'period_total': period_totals.get(category.key, 0.0),
        'average': averages.get(category.key, 0.0),
        'rules': [{'rule': rule, 'hits': hits[(category.key, index)], 'average': rule_averages.get((category.key, index), 0.0)}
                  for index, rule in enumerate(category.rules)],
    } for category in ledger.categories]



def _planned_accounts(config) -> dict[str, list[dict]]:
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
            'per_event': item.price_per_serving or 0,
            'workday':  False,
        })

    for entry in read_yaml(config.expenses_db / 'recurring.yaml') or []:
        cost = entry.get('cost_aed', 0) or 0
        freq = entry.get('frequency', 'monthly')
        monthly = _to_monthly(cost, freq)
        accounts.setdefault(entry.get('account', 'other'), []).append({
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
    return accounts


def _category_budgets(accounts: dict[str, list[dict]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for rows in accounts.values():
        for r in rows:
            cat = r.get('category') or 'Other'
            totals[cat] = totals.get(cat, 0.0) + r['monthly']
    return totals


def _aggregate_by_store_category(rows: list[dict]) -> list[dict]:
    totals: dict[tuple[str, str], float] = {}
    for r in rows:
        key = (r['store'], r['category'])
        totals[key] = totals.get(key, 0.0) + r['monthly']
    return [
        {'store': store, 'category': category, 'monthly': total}
        for (store, category), total in sorted(totals.items(), key=lambda kv: (kv[0][1], kv[0][0]))
    ]


def _account_sections(accounts: dict[str, list[dict]]) -> list[dict]:
    sections = []
    for account in expense_accounts():
        raw = accounts.get(account.key, [])
        if not raw:
            continue
        sections.append({
            'name':        account.key,
            'tracking':    account.tracking,
            'rows':        _aggregate_by_store_category(raw) if account.tracking == 'monthly' else raw,
            'total':       sum(r['monthly'] for r in raw),
            'daily_total': sum(r['daily'] for r in raw),
        })
    return sections


def _period_summary(ledger, period, budgets: dict[str, float], current: bool) -> dict:
    rows = _budget_rows(ledger.between(period.start, period.end), budgets, period)
    actual = sum(r['actual'] for r in rows)
    budget = sum(budgets.values())
    status, _ = _budget_status(budget, actual, period.fraction)
    return {
        'name': f'{period.day(period.length_days):%B %Y}',
        'range': period.label if current else period.range_label,
        'start': period.start.isoformat(),
        'current': current,
        'actual': actual,
        'budget': budget,
        'pct': min(actual / budget * 100, 100) if budget > 0 else 0,
        'status': status,
        'rows': rows,
    }


def _monthly_averages(ledger, current) -> tuple[dict, dict, dict]:
    totals: dict[datetime, float] = {}
    by_category: dict[str, dict[datetime, float]] = {}
    by_rule: dict[tuple[str, int], dict[datetime, float]] = {}
    for entry in ledger.visible:
        if not entry.spend:
            continue
        start = ledger.clock.period(entry.tx.at).start
        totals[start] = totals.get(start, 0.0) + entry.tx.aed
        if entry.category:
            months = by_category.setdefault(entry.category.key, {})
            months[start] = months.get(start, 0.0) + entry.tx.aed
        if entry.match and not entry.tx.category_override:
            months = by_rule.setdefault((entry.match.category.key, entry.match.index), {})
            months[start] = months.get(start, 0.0) + entry.tx.aed
    complete = [start for start in sorted(totals)[1:] if start < current.start]
    count = len(complete) or 1

    def average(months: dict[datetime, float]) -> float:
        return sum(months.get(start, 0.0) for start in complete) / count

    return (
        {'amount': average(totals), 'months': len(complete)},
        {key: average(months) for key, months in by_category.items()},
        {key: average(months) for key, months in by_rule.items()},
    )


def _env(ledger):
    tones = colors_for(c.name for c in ledger.categories)
    env = make_env(HERE)
    env.globals['tone'] = lambda name: tones.get(name, 'var(--faint)')
    env.filters['fmt'] = lambda v: f'{v:,.0f}'
    env.filters['fmt1'] = lambda v: f'{v:.1f}'
    env.filters['compact'] = lambda v: f'{v / 1000:.1f}k'.replace('.0k', 'k') if abs(v) >= 1000 else f'{v:,.0f}'
    return env


def render_previous_periods(services, before: str, count: int) -> str:
    config = services.config
    ledger = Ledger.load(config)
    budgets = _category_budgets(_planned_accounts(config))
    earliest = ledger.earliest
    summaries = []
    period = ledger.clock.period(datetime.fromisoformat(before) - timedelta(seconds=1))
    while len(summaries) < count and earliest is not None and period.end > earliest:
        summaries.append(_period_summary(ledger, period, budgets, current=False))
        period = ledger.clock.previous(period)
    more = earliest is not None and period.end > earliest
    return _env(ledger).get_template('periods.html').render(periods=summaries, more=more)


def render_card_periods(services, account: str, before: str, count: int) -> str:
    ledger = Ledger.load(services.config)
    earliest = ledger.earliest
    periods = []
    period = ledger.clock.period(datetime.fromisoformat(before) - timedelta(seconds=1))
    while len(periods) < count and earliest is not None and period.end > earliest:
        entries = sorted((e for e in ledger.between(period.start, period.end) if e.account == account),
                         key=lambda e: e.tx.ts, reverse=True)
        if entries:
            periods.append({
                'name': f'{period.day(period.length_days):%B %Y}',
                'start': period.start.isoformat(),
                'total': sum(e.tx.aed for e in entries if e.spend),
                'entries': entries,
            })
        period = ledger.clock.previous(period)
    more = earliest is not None and period.end > earliest
    return _env(ledger).get_template('card_periods.html').render(periods=periods, more=more, categories=ledger.categories)


def render(services) -> str:
    config = services.config
    accounts = _planned_accounts(config)
    account_sections = _account_sections(accounts)
    budgets = _category_budgets(accounts)
    ledger = Ledger.load(config)
    clock = ledger.clock
    period = clock.period(datetime.now(timezone.utc))
    period_entries = ledger.between(period.start, period.end)
    average, category_averages, rule_averages = _monthly_averages(ledger, period)

    return _env(ledger).get_template('expenses.html').render(
        account_sections=account_sections,
        grand_total=sum(s['total'] for s in account_sections),
        grand_daily=sum(s['daily_total'] for s in account_sections),
        by_category=sorted(budgets.items(), key=lambda kv: -kv[1]),
        current_period=_period_summary(ledger, period, budgets, current=True),
        average=average,
        card_sections=_card_sections(config, period_entries),
        categories=ledger.categories,
        category_cards=_category_cards(ledger, period_entries, category_averages, rule_averages),
        slots=clock.slots,
        types=tx_service.type_keys(config),
        uncategorized=ledger.uncategorized_vendors(),
    )
