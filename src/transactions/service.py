import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import messaging.service as messaging
import yaml

from pkg.model.io import read_yaml
from transactions import fx

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
_LOCATION_SUFFIX = re.compile(r',[^,]*$')


def _dir(config):
    return config.db / 'transactions'


def _patterns(config):
    return read_yaml(_dir(config) / 'patterns.yaml') or []


def _cards(config):
    return read_yaml(_dir(config) / 'cards.yaml') or []


def _autolabel(config):
    return read_yaml(_dir(config) / 'autolabel.yaml') or []


def _types(config) -> dict[str, dict]:
    return {t['key']: t for t in read_yaml(_dir(config) / 'types.yaml') or []}


def counts_as_spend(config, tx: dict) -> bool:
    kind = _types(config).get(tx.get('type'))
    if kind is None:
        raise ValueError(f"transaction {tx.get('id')} has type {tx.get('type')!r}, missing from transactions/types.yaml")
    return bool(kind.get('spend'))


def _num(value):
    return float(value.replace(',', '')) if value else None


def _matches(match, text):
    if match.startswith('re:'):
        return re.search(match[3:], text, re.I) is not None
    return match.lower() in text.lower()


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
            'last4': fields['last4'][-4:] if fields.get('last4') else None,
            'card_name': (fields.get('card_name') or '').strip(),
            'venue': (fields.get('venue') or '').strip(),
            'remaining': _num(fields.get('remaining')),
            'pattern': pattern['name'],
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
    return f"card …{parsed['last4']}" if parsed.get('last4') else 'Unknown'


def _autolabel_rule(parsed, rules) -> dict:
    hay = f"{parsed.get('venue', '')} {parsed.get('type', '')}"
    return next((rule for rule in rules if _matches(rule.get('match', ''), hay)), {})


def _signature(tx):
    return f"{tx.get('last4') or tx['account']}|{tx['amount']:.2f}|{tx['ts'][:10]}|{tx.get('remaining')}"


def _month_path(config, ts):
    return _dir(config) / f'{ts[:7]}.jsonl'


def _read_month(config, ts) -> list[dict]:
    path = _month_path(config, ts)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def transactions(config, month=None):
    ts = f'{month}-01' if month else datetime.now(timezone.utc).isoformat()
    return _read_month(config, ts)


def account_names(config) -> list[str]:
    return list(dict.fromkeys(card['display'] for card in _cards(config)))


def vendor_of(venue: str) -> str:
    return ' '.join(_LOCATION_SUFFIX.sub('', venue or '').split())


def _all_transactions(config) -> list[dict]:
    return [row for path in sorted(_dir(config).glob('*.jsonl')) for row in _read_month(config, path.stem)]


def uncategorized_vendors(config) -> list[dict]:
    totals: dict[str, dict] = {}
    for tx in _all_transactions(config):
        if tx.get('category_override') or tx.get('category') or not counts_as_spend(config, tx):
            continue
        vendor = vendor_of(tx['venue'])
        if not vendor:
            continue
        entry = totals.setdefault(vendor.casefold(), {'vendor': vendor, 'total': 0.0, 'count': 0, 'last': ''})
        entry['total'] += tx.get('amount_aed') or 0
        entry['count'] += 1
        entry['last'] = max(entry['last'], tx['ts'][:10])
    return sorted(totals.values(), key=lambda entry: -entry['total'])


def categorize_vendor(config, vendor: str, category: str) -> int:
    rules = [rule for rule in _autolabel(config) if rule.get('match', '').casefold() != vendor.casefold()]
    rules.append({'match': vendor, 'category': category})
    (_dir(config) / 'autolabel.yaml').write_text(yaml.safe_dump(rules, allow_unicode=True, sort_keys=False))
    updated = 0
    for path in _dir(config).glob('*.jsonl'):
        rows = _read_month(config, path.stem)
        matching = [row for row in rows if not row.get('category_override') and not row.get('category')
                    and vendor_of(row['venue']).casefold() == vendor.casefold()]
        for row in matching:
            row['category'], row['category_source'] = category, 'auto'
        if matching:
            _write_month(path, rows)
            updated += len(matching)
    return updated


def label_categories(config):
    return sorted({r.get('category', '') for r in _autolabel(config) if r.get('category')})


def _update(config, tx_id, **fields) -> bool:
    for path in sorted(_dir(config).glob('*.jsonl'), reverse=True):
        rows = _read_month(config, path.stem)
        row = next((r for r in rows if r.get('id') == tx_id), None)
        if row is None:
            continue
        row.update(fields)
        _write_month(path, rows)
        return True
    return False


def set_category(config, tx_id, category):
    return _update(config, tx_id, category_override=category, category_source='manual' if category else 'auto')


def set_note(config, tx_id, note):
    return _update(config, tx_id, note=note)


def _write_month(path, rows):
    path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')


def _repeated(config, entry, text):
    ts = entry.get('received_at') or ''
    return any(
        e.get('received_at', '') < ts and messaging.text_of(e.get('payload')) == text
        for e in messaging.inbox(config, ts[:7] or None)
    )


def _alert_text(parsed, account):
    return parsed['alert'].format_map(defaultdict(str, parsed['groups'], account=account))


def _record(config, entry, text, parsed, account):
    ts = entry.get('received_at') or datetime.now(timezone.utc).isoformat()
    rule = _autolabel_rule(parsed, _autolabel(config))
    category = rule.get('category', '')
    rate = fx.rate(config, parsed['currency'], ts[:10])
    tx = {
        'id': hashlib.sha1(f"{ts}|{text}".encode()).hexdigest()[:12],
        'ts': ts,
        'source': entry.get('source', ''),
        'account': account,
        'last4': parsed.get('last4'),
        'type': rule.get('type', parsed['type']),
        'amount': parsed['amount'],
        'currency': parsed['currency'],
        'amount_aed': round(parsed['amount'] * rate, 2) if rate is not None else None,
        'fx_rate': rate,
        'venue': parsed['venue'],
        'remaining': parsed['remaining'],
        'category': category,
        'category_source': 'auto' if category else '',
        'category_override': '',
        'pattern': parsed['pattern'],
        'raw_ref': entry.get('received_at', ''),
    }
    if _signature(tx) in {_signature(row) for row in _read_month(config, ts)}:
        return None
    path = _month_path(config, ts)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(tx, ensure_ascii=False) + '\n')
    return tx


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


def _manual_edits(config) -> dict[str, dict]:
    return {
        row['id']: {key: row[key] for key in ('category_override', 'category_source', 'note') if key in row}
        for row in _all_transactions(config)
        if row.get('category_source') == 'manual' or row.get('note')
    }


def backfill(config, rebuild=False):
    manual = _manual_edits(config) if rebuild else {}
    if rebuild:
        for path in _dir(config).glob('*.jsonl'):
            path.unlink()
    results = [ingest(config, entry, notify=False)
               for entry in sorted(messaging.all_entries(config), key=lambda e: e.get('received_at', ''))]
    for tx_id, edits in manual.items():
        _update(config, tx_id, **edits)
    counts = Counter(r['action'] for r in results)
    lines = [f'{action}: {n}' for action, n in sorted(counts.items()) if action != 'none']
    lines += [f"alert (not sent): {r['message']}" for r in results if r['action'] == 'alert']
    lines += [f"unparsed: {r['text']}" for r in results if r['action'] == 'unparsed']
    return '\n'.join(lines) or 'nothing to backfill'
