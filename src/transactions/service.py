import hashlib
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import messaging.service as messaging

from pkg.model.io import read_yaml
from transactions import fx
from transactions.rules import Category, Clock, Rule, slug
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
_SAME_MOVEMENT_WINDOW = timedelta(days=1)
_CHARGES_TOLERANCE = 5.0
_UNKNOWN_ACCOUNT = 'Unknown'


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
    for pattern in patterns:
        m = re.search(_expand(pattern['regex']), text, re.I)
        if not m:
            continue
        fields = dict(pattern.get('set') or {})
        fields.update({k: v for k, v in m.groupdict().items() if v is not None})
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
    return None


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


def _repeated(config, entry, text):
    ts = entry.get('received_at') or ''
    return any(
        e.get('received_at', '') < ts and messaging.text_of(e.get('payload')) == text
        for e in messaging.inbox(config, ts[:7] or None)
    )


def _alert_text(parsed, account):
    return parsed['alert'].format_map(defaultdict(str, parsed['groups'], account=account))


def ingest(config, entry, notify=True):
    text = messaging.text_of(entry.get('payload'))
    parsed = parse_text(text, _patterns(config))
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
    if tx and parsed['alert'] and notify:
        messaging.send(config, 'notifications', _alert_text(parsed, account))
    return {'action': 'record', 'tx': tx} if tx else {'action': 'duplicate', 'pattern': parsed['pattern']}


def _is_live(entry, now: datetime) -> bool:
    return now - datetime.fromisoformat(entry['received_at']) <= _LIVE_WINDOW


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


def _store(config) -> TransactionStore:
    return TransactionStore(_dir(config))


def _record(config, entry, text, parsed, account) -> Transaction | None:
    ts = entry.get('received_at') or datetime.now(timezone.utc).isoformat()
    rate = fx.rate(config, parsed['currency'], ts[:10])
    tx = Transaction(
        id=hashlib.sha1(f"{ts}|{text}".encode()).hexdigest()[:12],
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
    existing = _same_movement(store, tx)
    if existing is None:
        store.append(tx)
        return tx
    if parsed['enriches'] > _enrichment_rank(config, existing) and existing.venue != tx.venue:
        store.update(existing.id, venue=tx.venue, venue_pattern=tx.pattern)
    if existing.account == _UNKNOWN_ACCOUNT and tx.account != _UNKNOWN_ACCOUNT:
        store.update(existing.id, account=tx.account, last4=tx.last4, amount=tx.amount, amount_aed=tx.amount_aed)
    if existing.remaining is None and tx.remaining is not None:
        store.update(existing.id, remaining=tx.remaining)
    return None


def _enrichment_rank(config, tx: Transaction) -> int:
    source = tx.venue_pattern or tx.pattern
    return next((int(p.get('enriches') or 0) for p in _patterns(config) if p['name'] == source), 0)


def _same_movement(store: TransactionStore, tx: Transaction) -> Transaction | None:
    months = {f'{tx.at + shift:%Y-%m}' for shift in (-_SAME_MOVEMENT_WINDOW, timedelta(), _SAME_MOVEMENT_WINDOW)}
    rows = [row for month in sorted(months) for row in store.read_month(month)]
    exact = next((row for row in rows if row.signature == tx.signature), None)
    if exact is not None:
        return exact
    return next((row for row in rows
                 if (row.remaining is None or tx.remaining is None)
                 and abs(row.at - tx.at) <= _SAME_MOVEMENT_WINDOW
                 and _same_account_and_amount(row, tx)), None)


def _same_account_and_amount(row: Transaction, tx: Transaction) -> bool:
    if row.account == tx.account:
        return round(row.amount, 2) == round(tx.amount, 2)
    if _UNKNOWN_ACCOUNT in (row.account, tx.account):
        return 0 <= abs(row.amount - tx.amount) <= _CHARGES_TOLERANCE
    return False


def _overrides(config) -> dict[str, dict]:
    return {
        tx.id: {'category_override': tx.category_override, 'note': tx.note}
        for tx in _store(config).all() if tx.category_override or tx.note
    }


def backfill(config, rebuild=False):
    overrides = _overrides(config) if rebuild else {}
    if rebuild:
        _store(config).clear()
    results = [ingest(config, entry, notify=False)
               for entry in sorted(messaging.all_entries(config), key=lambda e: e.get('received_at', ''))]
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


def save_category(config, key: str, name: str, rules: list[dict]) -> Category:
    category = Category.objects.get(key=key)
    clock, types = Clock.load(config.db), set(type_keys(config))
    parsed = [Rule.model_validate(rule) for rule in rules]
    for rule in parsed:
        if not rule.match.strip():
            raise ValueError('every rule needs a match')
        for slot in rule.slots:
            if clock.slot(slot) is None:
                raise ValueError(f'unknown time slot {slot!r}')
        if rule.type and rule.type not in types:
            raise ValueError(f'unknown transaction type {rule.type!r}')
        if rule.is_pattern:
            try:
                re.compile(rule.match[3:])
            except re.error as error:
                raise ValueError(f'invalid pattern {rule.match!r}: {error}') from error
    category.name = name.strip() or category.name
    category.rules = parsed
    category.save()
    return category


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


def categorize_vendor(vendor: str, category_key: str) -> Category:
    category = Category.objects.get(key=category_key)
    if not any(rule.match.casefold() == vendor.casefold() and not rule.slots for rule in category.rules):
        category.rules = category.rules + [Rule(match=vendor)]
        category.save()
    return category
