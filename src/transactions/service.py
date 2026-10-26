import hashlib
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import messaging.service as messaging
import yaml

from pkg.model.io import read_yaml
from transactions import fx
from transactions.rules import Category, Clock, Matching, Rule, slug
from transactions.transaction import UNCATEGORIZED, Transaction, TransactionStore

_NUMBER = r'(?:\d[\d,]*(?:\.\d+)?|\.\d+)'
_TOKENS = {
    'amount': f'(?P<amount>{_NUMBER})',
    'remaining': f'(?P<remaining>-?{_NUMBER})',
    'currency': r'(?P<currency>[A-Z]{3})',
    'last4': r'(?P<last4>\d{4})',
    'account_no': r'(?P<last4>[\dX*]{4,})',
    'number': _NUMBER,
}
_AMOUNT_HINT = re.compile(r'\b(?:[A-Z]{3} ?(?:\d[\d,]*)?\.\d{2}|\d[\d,]*\.\d{2} ?[A-Z]{3})\b')
_TXN_HINT = re.compile(r'card|spent|withdrawal|purchase|available limit|avl bal', re.I)
_LIVE_WINDOW = timedelta(days=1)
_UNKNOWN_ACCOUNT = 'Unknown'
_PERIOD_START_REACH = timedelta(days=20)


def _dir(config):
    return config.db / 'transactions'


def _patterns(config):
    return read_yaml(_dir(config) / 'patterns.yaml') or []


def _cards(config):
    return read_yaml(_dir(config) / 'cards.yaml') or []


def _num(value):
    return float(value.replace(',', '')) if value else None


def _expand(regex):
    return re.sub(r'\{(\w+)\}', lambda m: _TOKENS.get(m[1], m[0]), regex)


def parse_text(text, patterns):
    records = []
    for pattern in patterns:
        parsed = _parse(pattern, text)
        if parsed is None:
            continue
        records.append(parsed)
        if not pattern.get('continue'):
            break
    return records


def _parse(pattern, text):
    m = re.search(_expand(pattern['regex']), text, re.I)
    if not m:
        return None
    fields = dict(pattern.get('set') or {})
    fields.update({k: v for k, v in m.groupdict().items() if v is not None})
    if 'beneficiary' in fields:
        fields['beneficiary'] = _person_name(fields['beneficiary'])
    if '{' in fields.get('venue', ''):
        fields['venue'] = fields['venue'].format_map(defaultdict(str, fields))
    amount = _num(fields.get('amount'))
    if amount is not None and pattern.get('negate'):
        amount = -amount
    return {
        'action': pattern.get('action', 'record'),
        'alert': pattern.get('alert', ''),
        'groups': fields,
        'type': fields.get('type', 'purchase'),
        'currency': (fields.get('currency') or '').upper() or None,
        'amount': amount,
        'last4': fields['last4'][-4:].replace('*', 'X') if fields.get('last4') else None,
        'card_name': (fields.get('card_name') or '').strip(),
        'venue': (fields.get('venue') or '').strip(),
        'remaining': _num(fields.get('remaining')),
        'pattern': pattern['name'],
        'enriches': int(pattern.get('enriches') or 0),
    }


def _person_name(name: str) -> str:
    name = ' '.join(name.split())
    return name.title() if name.isupper() and '*' not in name else name


def looks_like_transaction(text):
    return bool(_AMOUNT_HINT.search(text) and _TXN_HINT.search(text))


def _account(parsed, cards):
    for card in cards:
        if parsed.get('last4') and card.get('last4') == parsed['last4']:
            return card['display']
        if card.get('name') and card['name'].lower() in parsed.get('card_name', '').lower():
            return card['display']
    if parsed.get('card_name'):
        return parsed['card_name']
    return f"card …{parsed['last4']}" if parsed.get('last4') else _UNKNOWN_ACCOUNT


def _received_at(entry) -> datetime:
    return datetime.fromisoformat(entry['received_at'])


def _repeated(config, entry, text):
    at = _received_at(entry)
    return any(
        _received_at(e) < at and messaging.text_of(e.get('payload')) == text
        for e in messaging.inbox(config, f'{at:%Y-%m}')
    )


def _alert_text(parsed, account):
    return parsed['alert'].format_map(defaultdict(str, parsed['groups'], account=account))


def ingest(config, entry, notify=True):
    text = messaging.text_of(entry.get('payload'))
    records = parse_text(text, _patterns(config))
    parsed = records[0] if records else None
    if parsed is None or (parsed['action'] == 'record' and parsed['amount'] is None):
        if not looks_like_transaction(text):
            return {'action': 'none'}
        if notify and not _repeated(config, entry, text):
            messaging.send(config, 'notifications', 'Unparsed transaction — add a pattern:\n\n' + text)
        return {'action': 'unparsed', 'text': text}
    if parsed['action'] == 'ignore':
        return {'action': 'ignore', 'pattern': parsed['pattern']}
    if _repeated(config, entry, text):
        return {'action': 'repeat', 'pattern': parsed['pattern']}
    account = _account(parsed, _cards(config))
    if parsed['action'] == 'alert':
        message = _alert_text(parsed, account)
        if notify:
            messaging.send(config, 'notifications', message)
        return {'action': 'alert', 'message': message}
    tx = _record(config, entry, text, parsed, account)
    for follow_up in records[1:]:
        if follow_up['action'] == 'record' and follow_up['amount'] is not None:
            _record(config, entry, text, follow_up, _account(follow_up, _cards(config)), follow_up['pattern'])
    if tx and parsed['alert'] and notify:
        messaging.send(config, 'notifications', _alert_text(parsed, account))
    return {'action': 'record', 'tx': tx} if tx else {'action': 'duplicate', 'pattern': parsed['pattern']}


def _is_live(entry, now: datetime) -> bool:
    return now - _received_at(entry) <= _LIVE_WINDOW


def receive(config, source: str, payloads: list) -> Counter:
    now = datetime.now(timezone.utc)
    outcome = Counter()
    for payload in payloads:
        entry = messaging.ingest(config, source, payload)
        if entry is None:
            outcome['duplicate message'] += 1
            continue
        outcome[ingest(config, entry, notify=_is_live(entry, now))['action']] += 1
    return outcome


def receive_wallet(config, request: dict) -> Counter:
    field = lambda *names: next((_wallet_text(request.get(name)) for name in names if _wallet_text(request.get(name))), '')
    text = f"Apple Pay: spent {field('amount')} at {field('merchant')} with {field('card_or_pass', 'card')}"
    return receive(config, 'wallet', [{'text': text, 'sender': 'Apple Wallet', 'raw': request}])


def _wallet_text(value) -> str:
    if isinstance(value, dict):
        return _wallet_text(value.get('name') or value.get('title') or '')
    return str(value or '').strip()


def _store(config) -> TransactionStore:
    return TransactionStore(_dir(config))


def _record(config, entry, text, parsed, account, follow_up='') -> Transaction | None:
    ts = Clock.load(config.db).local(_received_at(entry)).isoformat()
    rate = fx.rate(config, parsed['currency'], ts[:10])
    seed = f'{ts}|{text}|{follow_up}' if follow_up else f'{ts}|{text}'
    tx = Transaction(
        id=hashlib.sha1(seed.encode()).hexdigest()[:12],
        ts=ts,
        source=entry.get('source', ''),
        account=account,
        last4=parsed.get('last4'),
        type=parsed['type'],
        amount=parsed['amount'],
        currency=parsed['currency'],
        amount_aed=round(parsed['amount'] * rate, 2) if rate is not None else None,
        fx_rate=rate,
        venue=parsed['venue'],
        remaining=parsed['remaining'],
        pattern=parsed['pattern'],
        raw_ref=entry.get('received_at', ''),
    )
    store = _store(config)
    existing = _same_movement(config, store, tx)
    if existing is None:
        store.append(tx)
        return tx
    if parsed['enriches'] > _enrichment_rank(config, existing):
        store.update(existing.id, venue=tx.venue, venue_pattern=tx.pattern, type=tx.type)
    if existing.account == _UNKNOWN_ACCOUNT and tx.account != _UNKNOWN_ACCOUNT:
        store.update(existing.id, account=tx.account, last4=tx.last4, amount=tx.amount, amount_aed=tx.amount_aed,
                     remaining=tx.remaining, source=tx.source, pattern=tx.pattern)
    if existing.remaining is None and tx.remaining is not None:
        store.update(existing.id, remaining=tx.remaining)
    return None


def _enrichment_rank(config, tx: Transaction) -> int:
    source = tx.venue_pattern or tx.pattern
    return next((int(p.get('enriches') or 0) for p in _patterns(config) if p['name'] == source), 0)


def _same_movement(config, store: TransactionStore, tx: Transaction) -> Transaction | None:
    matching = Matching.load(config.db)
    window = matching.same_movement
    months = {f'{tx.at + shift:%Y-%m}' for shift in (-window, timedelta(), window)}
    rows = [row for month in sorted(months) for row in store.read_month(month)]
    exact = next((row for row in rows if row.signature == tx.signature and not _distinct_events(row, tx, matching)), None)
    if exact is not None:
        return exact
    patterns = {pattern['name']: pattern for pattern in _patterns(config)}
    banks = {card['display']: card.get('bank', '') for card in _cards(config)}
    return next((row for row in rows
                 if (row.remaining is None or tx.remaining is None)
                 and not _distinct_events(row, tx, matching)
                 and abs(row.at - tx.at) <= window
                 and _compatible_types(row, tx, patterns)
                 and _same_account_and_amount(row, tx, patterns, banks, matching.charges_aed)), None)


def _distinct_events(row: Transaction, tx: Transaction, matching: Matching) -> bool:
    return (row.pattern == tx.pattern and row.remaining is None and tx.remaining is None
            and abs(row.at - tx.at) > matching.repeat_gap)


def _compatible_types(row: Transaction, tx: Transaction, patterns: dict) -> bool:
    if row.type == tx.type:
        return True
    merges = lambda a, b: b.type in (patterns.get(a.pattern) or {}).get('merges_with', [])
    return merges(row, tx) or merges(tx, row)


def _same_account_and_amount(row: Transaction, tx: Transaction, patterns: dict, banks: dict, charges: float) -> bool:
    if row.account == tx.account:
        return round(row.amount, 2) == round(tx.amount, 2)
    if _UNKNOWN_ACCOUNT not in (row.account, tx.account):
        return False
    unknown, known = (row, tx) if row.account == _UNKNOWN_ACCOUNT else (tx, row)
    bank = (patterns.get(unknown.pattern) or {}).get('bank')
    if bank and banks.get(known.account) != bank:
        return False
    return abs(row.amount - tx.amount) <= charges


def _overrides(config) -> dict[str, dict]:
    return {
        tx.id: {'category_override': tx.category_override, 'note': tx.note,
                'description_override': tx.description_override, 'voided': tx.voided, 'marked_settled': tx.marked_settled}
        for tx in _store(config).all()
        if tx.category_override or tx.note or tx.description_override or tx.voided or tx.marked_settled
    }


def backfill(config, rebuild=False):
    overrides = _overrides(config) if rebuild else {}
    if rebuild:
        _store(config).clear()
    results = [ingest(config, entry, notify=False)
               for entry in sorted(messaging.all_entries(config), key=_received_at)]
    for tx_id, fields in overrides.items():
        _store(config).update(tx_id, **fields)
    counts = Counter(r['action'] for r in results)
    lines = [f'{action}: {n}' for action, n in sorted(counts.items()) if action != 'none']
    lines += [f"alert (not sent): {r['message']}" for r in results if r['action'] == 'alert']
    lines += [f"unparsed: {r['text']}" for r in results if r['action'] == 'unparsed']
    return '\n'.join(lines) or 'nothing to backfill'


def transactions(config, month=None) -> list[Transaction]:
    return _store(config).read_month(month or f'{datetime.now(timezone.utc):%Y-%m}')


def account_names(config) -> list[str]:
    return list(dict.fromkeys(card['display'] for card in _cards(config)))


def type_keys(config) -> list[str]:
    return [t['key'] for t in read_yaml(_dir(config) / 'types.yaml') or []]


def set_category(config, tx_id: str, category_key: str) -> bool:
    if category_key not in ('', UNCATEGORIZED) and Category.objects.get_or_none(key=category_key) is None:
        raise ValueError(f'unknown category {category_key!r}')
    return _store(config).update(tx_id, category_override=category_key)


def set_description(config, tx_id: str, description: str) -> bool:
    return _store(config).update(tx_id, description_override=' '.join(description.split()))


def set_voided(config, tx_id: str, voided: bool) -> bool:
    return _store(config).update(tx_id, voided=voided)


def set_settled(config, tx_id: str, settled: bool) -> bool:
    return _store(config).update(tx_id, marked_settled=settled)


def set_note(config, tx_id: str, note: str) -> bool:
    return _store(config).update(tx_id, note=note)


def create_category(name: str) -> Category:
    key = slug(name)
    if not key:
        raise ValueError('category name is empty')
    if Category.objects.get_or_none(key=key) is not None:
        raise ValueError(f'category {name!r} already exists')
    category = Category(key=key, name=name.strip())
    category.save()
    return category


def end_period_at(config, ledger, period_key: str, tx_id: str) -> str:
    following = ledger.following_key(period_key)
    first = ledger.entry_after(tx_id)
    if following is None or first is None:
        raise ValueError('no later transaction to start the next period with')
    year, month = map(int, following.split('-'))
    if abs(first.tx.at - Clock.load(config.db).default_period_start(year, month)) > _PERIOD_START_REACH:
        raise ValueError(f'{first.tx.ts[:10]} is too far from the usual start of that period')
    path = _dir(config) / 'period_starts.yaml'
    starts = read_yaml(path) or {}
    starts[following] = first.tx.id
    path.write_text(yaml.safe_dump(dict(sorted(starts.items())), sort_keys=False))
    return following


def rename_category(key: str, name: str) -> Category:
    category = Category.objects.get(key=key)
    if not name.strip():
        raise ValueError('category name is empty')
    category.name = name.strip()
    category.save()
    return category


def assign_vendor(config, vendor: str, assignments: list[dict]) -> None:
    clock = Clock.load(config.db)
    current = [rule for category in Category.objects.all() for rule in category.rules
               if rule.match.casefold() == vendor.casefold()]
    type_override = next((rule.type for rule in current if rule.type), '')
    rules: dict[str, list[Rule]] = {}
    for assignment in assignments:
        slots = list(assignment.get('slots') or [])
        for slot in slots:
            if clock.slot(slot) is None:
                raise ValueError(f'unknown time slot {slot!r}')
        if assignment.get('category'):
            Category.objects.get(key=assignment['category'])
            rules.setdefault(assignment['category'], []).append(
                Rule(match=vendor, slots=slots, note=(assignment.get('note') or '').strip(), type=type_override))
    for category in Category.objects.all():
        kept = [rule for rule in category.rules if rule.match.casefold() != vendor.casefold()]
        updated = kept + rules.get(category.key, [])
        if updated != category.rules:
            category.rules = updated
            category.save()


def delete_category(config, key: str, move_rules_to: str = '') -> int:
    category = Category.objects.get(key=key)
    if move_rules_to:
        target = Category.objects.get(key=move_rules_to)
        target.rules = target.rules + category.rules
        target.save()

    def release(tx: Transaction) -> bool:
        if tx.category_override != key:
            return False
        tx.category_override, tx.note = UNCATEGORIZED, ''
        return True

    released = _store(config).update_each(release)
    category.delete()
    return released
