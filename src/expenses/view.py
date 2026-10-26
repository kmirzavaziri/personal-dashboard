from collections import Counter
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import transactions.service as tx_service
from transactions.ledger import Ledger
from transactions.rules import Category
from transactions.transaction import UNCATEGORIZED
from core.item.schedule import build_pool
from core.labels import colors_for
from core.web.templating import make_env
from core.item.categories import EdibleCategory
from expenses.reference import expense_category
from pkg.model.io import read_yaml

HERE = Path(__file__).parent

_DAYS_PER_MONTH = 365.25 / 12

_AVERAGE_MONTHS = 6
_MISC = 'Misc.'
_MISC_KEY = ''
_MISC_NODE = 'unbudgeted'
_ALL_SPENDING = 'All spending'

_WORKDAYS_PER_MONTH = _DAYS_PER_MONTH * 5 / 7

_FREQ_TO_MONTHLY = {
    'daily':    _DAYS_PER_MONTH,
    'workday':  _WORKDAYS_PER_MONTH,
    'weekly':   _DAYS_PER_MONTH / 7,
    'biweekly': _DAYS_PER_MONTH / 14,
    'monthly':  1.0,
    'yearly':   1.0 / 12,
}

_FREQ_UNITS = {
    'daily':    '/ day',
    'workday':  '/ workday',
    'weekly':   '/ week',
    'biweekly': '/ 2 weeks',
    'monthly':  '',
    'yearly':   '/ year',
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
    names = _category_names()
    actual_by_cat: dict[str, float] = {}
    count_by_cat: Counter = Counter()
    for entry in entries:
        if entry.counts_as_spending:
            key = entry.category.key if entry.category else ''
            actual_by_cat[key] = actual_by_cat.get(key, 0.0) + entry.aed
            count_by_cat[key] += 1

    budgeted = {cat for cat, budget in cat_totals.items() if budget > 0 and cat != _MISC_KEY}
    misc_parts = sorted(({'category': names[cat] if cat else 'Uncategorized', 'actual': actual, 'count': count_by_cat[cat]}
                         for cat, actual in actual_by_cat.items() if cat not in budgeted), key=lambda part: -part['actual'])
    misc = sum(part['actual'] for part in misc_parts)
    rows = []
    for cat in budgeted:
        budget = cat_totals[cat]
        actual = actual_by_cat.get(cat, 0.0)
        status, _ = _budget_status(budget, actual, period.fraction)
        rows.append({
            'category': names[cat],
            'budget': budget,
            'actual': actual,
            'pct': min(actual / budget * 100, 100) if budget > 0 else 0,
            'status': status,
        })
    rows.sort(key=lambda r: ({'red': 0, 'yellow': 1, 'green': 2, 'none': 3}[r['status']], -r['actual']))
    misc_budget = cat_totals.get(_MISC_KEY, 0.0)
    if misc or misc_budget:
        status, _ = _budget_status(misc_budget, misc, period.fraction)
        rows.append({'category': _MISC, 'budget': misc_budget, 'actual': misc, 'status': status, 'parts': misc_parts,
                     'pct': min(misc / misc_budget * 100, 100) if misc_budget > 0 else 0})
    return rows


def _card_sections(config, entries) -> list[dict]:
    cards: dict[str, list] = {name: [] for name in tx_service.account_names(config)}
    for entry in entries:
        cards.setdefault(entry.account or 'Unknown', []).append(entry)
    return [{
        'account': account,
        'total': sum(e.aed for e in entries if e.counts_as_spending and not e.hidden),
        'count': sum(1 for e in entries if not e.hidden and not e.self_transfer),
        'entries': sorted(entries, key=lambda e: e.tx.at, reverse=True),
    } for account, entries in cards.items()]


def _vendor_rows(ledger, type_keys: list[str]) -> list[dict]:
    assigned: dict[str, list] = {}
    for category in ledger.categories:
        for rule in category.rules:
            assigned.setdefault(rule.match.casefold(), []).append((category, rule))
    summaries = {row['vendor'].casefold(): row for row in ledger.vendor_summaries()}
    for key in type_keys:
        if key.casefold() in assigned and key.casefold() not in summaries:
            summaries[key.casefold()] = {'vendor': key, 'total': 0.0, 'count': 0, 'last': '', 'inflow': 0,
                                         'hidden_total': 0.0, 'hidden_count': 0, 'overridden': 0, 'by_type': Counter()}
    rows = []
    for folded, summary in summaries.items():
        rules = assigned.get(folded, [])
        split = any(rule.slots for _, rule in rules)
        per_slot = {slot: (category.key, rule.note) for category, rule in rules for slot in rule.slots}
        single = next(((category.key, rule.note) for category, rule in rules if not rule.slots), ('', ''))
        primary = single[0] if not split else next(iter(per_slot.values()), ('', ''))[0]
        by_type = '' if rules else next(iter(key for key, _ in summary['by_type'].most_common(1)), '')
        primary = primary or by_type
        hidden = summary['count'] == 0 and summary['hidden_count'] > 0
        rows.append({
            'hidden': hidden or (not rules and summary['count'] > 0 and summary['overridden'] == summary['count']),
            'vendor': summary['vendor'],
            'label': f"Any {summary['vendor'].replace('_', ' ')}" if summary['vendor'] in type_keys else summary['vendor'],
            'count': summary['hidden_count'] if hidden else summary['count'],
            'total': abs(summary['hidden_total'] if hidden else summary['total']),
            'last': summary['last'],
            'inflow': summary['inflow'] * 2 > summary['count'] if summary['count'] else summary['hidden_total'] < 0,
            'split': split,
            'single': single,
            'per_slot': per_slot,
            'type': next((rule.type for _, rule in rules if rule.type), ''),
            'by_type': by_type,
            'category': primary,
            'category_name': ledger.category(primary).name if ledger.category(primary) else '',
        })
    return sorted(rows, key=lambda row: -row['total'])


def _planned_lines(config) -> list[dict]:
    groups = {category.key: category.label for category in EdibleCategory.objects.all()}
    lines = []
    for item in sorted(build_pool(config).values(), key=lambda item: item.short_name):
        if item.metadata.edible.track_only or item.price_per_month is None or item.servings_per_week == 0:
            continue
        expense = expense_category(item.metadata.edible.category)
        if expense is None:
            continue
        lines.append({
            'name': item.short_name,
            'category_key': expense.category,
            'group': groups[item.metadata.edible.category],
            'url': item.url or '',
            'image': item.image or '',
            'note': '',
            'monthly': item.price_per_month,
            'cost': 0.0,
            'unit': '',
        })
    for entry in read_yaml(config.expenses_db / 'recurring.yaml') or []:
        cost = entry.get('cost_aed', 0) or 0
        frequency = entry.get('frequency', 'monthly')
        lines.append({
            'name': entry.get('name', ''),
            'category_key': entry.get('category', _MISC_KEY),
            'group': '',
            'url': '',
            'image': '',
            'note': entry.get('notes', ''),
            'monthly': _to_monthly(cost, frequency),
            'cost': cost,
            'unit': _FREQ_UNITS[frequency],
        })
    return lines


def _category_names() -> dict[str, str]:
    return {category.key: category.name for category in Category.objects.all()}


def _category_name(key: str, names: dict[str, str]) -> str:
    if key == _MISC_KEY:
        return _MISC
    if key not in names:
        raise ValueError(f'budget category {key!r} is not a transactions category')
    return names[key]


def _category_budgets(lines: list[dict]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for line in lines:
        totals[line['category_key']] = totals.get(line['category_key'], 0.0) + line['monthly']
    return totals


def _budget_tree(lines: list[dict], names: dict[str, str], averages: dict[str, float], average_total: float) -> list[dict]:
    by_category: dict[str, list[dict]] = {}
    for line in lines:
        by_category.setdefault(line['category_key'], []).append(line)
    tree = []
    for key, members in by_category.items():
        groups: dict[str, list[dict]] = {}
        children = []
        for line in members:
            if line['group']:
                groups.setdefault(line['group'], []).append(line)
            else:
                children.append(line)
        children += [{'name': name, 'monthly': sum(item['monthly'] for item in items),
                      'children': sorted(items, key=lambda item: -item['monthly'])} for name, items in groups.items()]
        tree.append({
            'key': key or _MISC_NODE,
            'name': _category_name(key, names),
            'monthly': sum(line['monthly'] for line in members),
            'average': averages.get(key, 0.0),
            'children': sorted(children, key=lambda child: -child['monthly']),
        })
    misc = next((node for node in tree if node['key'] == _MISC_NODE), None)
    if misc:
        misc['average'] = average_total - sum(averages.get(key, 0.0) for key in by_category if key != _MISC_KEY)
    return sorted(tree, key=lambda node: (node is misc, -node['monthly']))


def _period_summary(ledger, period, budgets: dict[str, float], current: bool) -> dict:
    rows = _budget_rows(ledger.between(period.start, period.end), budgets, period)
    actual = sum(r['actual'] for r in rows)
    budget = sum(budgets.values())
    status, _ = _budget_status(budget, actual, period.fraction)
    return {
        'name': period.name,
        'key': period.key,
        'range': period.label if current else period.range_label,
        'start': period.start.isoformat(),
        'current': current,
        'pace': period.fraction * 100,
        'actual': actual,
        'budget': budget,
        'pct': min(actual / budget * 100, 100) if budget > 0 else 0,
        'status': status,
        'rows': rows,
    }


def _monthly_averages(ledger, current) -> tuple[dict, dict]:
    totals: dict[datetime, float] = {}
    by_category: dict[str, dict[datetime, float]] = {}
    for entry in ledger.visible:
        if not entry.counts_as_spending:
            continue
        start = ledger.period(entry.tx.at).start
        totals[start] = totals.get(start, 0.0) + entry.aed
        if entry.category:
            months = by_category.setdefault(entry.category.key, {})
            months[start] = months.get(start, 0.0) + entry.aed
    complete = [start for start in sorted(totals)[1:] if start < current.start][-_AVERAGE_MONTHS:]
    count = len(complete) or 1

    def average(months: dict[datetime, float]) -> float:
        return sum(months.get(start, 0.0) for start in complete) / count

    return (
        {'amount': average(totals), 'months': len(complete)},
        {key: average(months) for key, months in by_category.items()},
    )


def _trends(ledger, now: datetime, budgets: dict[str, float]) -> dict:
    current = ledger.period(now)
    periods = []
    period = current
    while ledger.earliest is not None and period.end > ledger.earliest:
        periods.append(period)
        period = ledger.previous(period)
    periods.reverse()
    if not periods:
        return {'start': '', 'days': 0, 'periods': [], 'series': []}
    first_day = ledger.clock.local(periods[0].start).date()
    today = ledger.clock.local(now).date()
    series: dict[str, dict[int, float]] = {}
    for entry in ledger.visible:
        if not entry.counts_as_spending:
            continue
        day = (ledger.clock.local(entry.tx.at).date() - first_day).days
        if day < 0:
            continue
        for key in (_ALL_SPENDING, entry.category.key if entry.category else ''):
            amounts = series.setdefault(key, {})
            amounts[day] = amounts.get(day, 0.0) + entry.aed
    tones = colors_for(c.name for c in ledger.categories)
    names = {category.key: category.name for category in ledger.categories} | {_ALL_SPENDING: _ALL_SPENDING, '': 'Uncategorized'}
    return {
        'start': first_day.isoformat(),
        'days': (today - first_day).days + 1,
        'periods': [{'label': p.name, 'day': (ledger.clock.local(p.start).date() - first_day).days} for p in periods],
        'series': sorted(({
            'name': names[key],
            'tone': 'var(--accent)' if key == _ALL_SPENDING else tones.get(names[key], 'var(--faint)'),
            'daily': {day: round(amount, 2) for day, amount in amounts.items()},
            'budget': round(sum(budgets.values())) if key == _ALL_SPENDING else round(budgets.get(key, 0.0)),
        } for key, amounts in series.items()), key=lambda row: -sum(row['daily'].values())),
    }


def _env(ledger):
    return _env_for(tuple(c.name for c in ledger.categories), tuple(ledger.account_names))


@lru_cache(maxsize=4)
def _env_for(category_names: tuple[str, ...], account_names: tuple[str, ...]):
    tones = colors_for(category_names)
    card_tones = colors_for(account_names)
    env = make_env(HERE)
    env.trim_blocks, env.lstrip_blocks = True, True
    env.globals['tone'] = lambda name: tones.get(name, 'var(--faint)')
    env.globals['card_tone'] = lambda name: card_tones.get(name, 'var(--faint)')
    env.globals['uncategorized'] = UNCATEGORIZED
    env.filters['fmt'] = lambda v: f'{v:,.0f}'
    env.filters['fmt1'] = lambda v: f'{v:.1f}'
    env.filters['compact'] = lambda v: f'{v / 1000:.1f}k'.replace('.0k', 'k') if abs(v) >= 1000 else f'{v:,.0f}'
    return env


def render_previous_periods(services, before: str, count: int) -> str:
    config = services.config
    ledger = Ledger.load(config)
    budgets = _category_budgets(_planned_lines(config))
    earliest = ledger.earliest
    summaries = []
    period = ledger.period(datetime.fromisoformat(before) - timedelta(seconds=1))
    while len(summaries) < count and earliest is not None and period.end > earliest:
        summaries.append(_period_summary(ledger, period, budgets, current=False))
        period = ledger.previous(period)
    more = earliest is not None and period.end > earliest
    return _env(ledger).get_template('periods.html').render(periods=summaries, more=more)


def render_card_periods(services, account: str, before: str, count: int) -> str:
    ledger = Ledger.load(services.config)
    earliest = ledger.earliest
    periods = []
    period = ledger.period(datetime.fromisoformat(before) - timedelta(seconds=1))
    while len(periods) < count and earliest is not None and period.end > earliest:
        entries = sorted((e for e in ledger.all_between(period.start, period.end) if not account or e.account == account),
                         key=lambda e: e.tx.at, reverse=True)
        if entries:
            periods.append({
                'name': period.name,
                'key': period.key,
                'range': period.range_label,
                'start': period.start.isoformat(),
                'total': sum(e.aed for e in entries if e.counts_as_spending and not e.hidden),
                'count': sum(1 for e in entries if not e.hidden and not e.self_transfer),
                'entries': entries,
            })
        period = ledger.previous(period)
    more = earliest is not None and period.end > earliest
    return _env(ledger).get_template('card_periods.html').render(
        periods=periods, more=more, categories=ledger.categories, show_account=not account)


def _matches_query(entry, terms: list[str]) -> bool:
    haystack = ' '.join((entry.tx.description, entry.tx.venue, entry.note, entry.category_name, entry.account, entry.type,
                         f'{abs(entry.tx.aed):.2f}', f'{abs(entry.tx.amount):.2f}')).casefold()
    return all(term in haystack for term in terms)


def render_rows(services, ids: list[str], show_account: bool) -> str:
    ledger = Ledger.load(services.config)
    by_id = {entry.tx.id: entry for entry in ledger.entries}
    return _env(ledger).get_template('rows.html').render(
        entries=[by_id[tx_id] for tx_id in ids if tx_id in by_id], categories=ledger.categories, show_account=show_account)


def render_search(services, query: str, account: str, limit: int) -> str:
    ledger = Ledger.load(services.config)
    terms = query.casefold().split()
    hits = [e for e in reversed(ledger.entries)
            if (not account or e.account == account) and _matches_query(e, terms)] if terms else []
    entries = hits[:limit]
    return _env(ledger).get_template('search_results.html').render(
        entries=entries, truncated=len(hits) > limit, categories=ledger.categories, show_account=not account,
        total=sum(e.aed for e in hits if e.counts_as_spending and not e.hidden),
    )


def render_vendor_rows(services) -> str:
    config = services.config
    ledger = Ledger.load(config)
    return _env(ledger).get_template('vendor_rows.html').render(
        vendor_rows=_vendor_rows(ledger, tx_service.type_keys(config)),
        categories=ledger.categories,
        slots=ledger.clock.slots,
    )


def render(services) -> str:
    config = services.config
    lines = _planned_lines(config)
    budgets = _category_budgets(lines)
    ledger = Ledger.load(config)
    clock = ledger.clock
    period = ledger.period(datetime.now(timezone.utc))
    period_entries = ledger.between(period.start, period.end)
    shown_entries = ledger.all_between(period.start, period.end)
    average, category_averages = _monthly_averages(ledger, period)
    card_sections = _card_sections(config, shown_entries)
    category_names = {category.key: category.name for category in ledger.categories}
    trends = _trends(ledger, datetime.now(timezone.utc), budgets)

    return _env(ledger).get_template('expenses.html').render(
        budget_tree=_budget_tree(lines, category_names, category_averages, average['amount']),
        budget_total=sum(budgets.values()),
        budget_average=average['amount'],
        current_period=_period_summary(ledger, period, budgets, current=True),
        average=average,
        card_sections=card_sections,
        trends=trends,
        all_cards={
            'entries': sorted(shown_entries, key=lambda e: e.tx.at, reverse=True),
            'total': sum(e.aed for e in shown_entries if e.counts_as_spending and not e.hidden),
            'count': sum(1 for e in shown_entries if not e.hidden and not e.self_transfer),
        },
        categories=ledger.categories,
        category_averages=category_averages,
        slots=clock.slots,
        slot_json=[{'key': slot.key, 'label': slot.label, 'short': slot.short} for slot in clock.slots],
        types=tx_service.type_keys(config),
    )
