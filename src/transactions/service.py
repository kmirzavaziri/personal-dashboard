import hashlib
import json
import re
from datetime import datetime, timezone

import messaging.service as messaging
from pkg.model.io import read_yaml

_AMOUNT_HINT = re.compile(r'(?:AED|USD)\s*[\d,]+\.\d{2}', re.I)
_TXN_HINT = re.compile(r'card|spent|withdrawal|purchase|available limit|avl bal', re.I)


def _dir(config):
    return config.db / 'transactions'


def _patterns(config):
    return read_yaml(_dir(config) / 'patterns.yaml') or []


def _cards(config):
    return read_yaml(_dir(config) / 'cards.yaml') or []


def _autolabel(config):
    return read_yaml(_dir(config) / 'autolabel.yaml') or []


def _num(value):
    return float(value.replace(',', '')) if value else None


def _text_of(payload):
    return payload.get('text', '') if isinstance(payload, dict) else str(payload)


def _matches(match, text):
    if match.startswith('re:'):
        return re.search(match[3:], text, re.I) is not None
    return match.lower() in text.lower()


def parse_text(text, patterns):
    for pattern in patterns:
        m = re.search(pattern['regex'], text, re.I)
        if not m:
            continue
        fields = dict(pattern.get('set') or {})
        fields.update({k: v for k, v in m.groupdict().items() if v is not None})
        return {
            'type': fields.get('type', 'purchase'),
            'currency': fields.get('currency'),
            'amount': _num(fields.get('amount')),
            'last4': fields.get('last4'),
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


def _auto_category(parsed, rules):
    hay = f"{parsed.get('venue', '')} {parsed.get('type', '')}"
    for rule in rules:
        if _matches(rule.get('match', ''), hay):
            return rule.get('category', '')
    return ''


def _signature(tx):
    return f"{tx.get('last4') or tx['account']}|{tx['amount']:.2f}|{tx['ts'][:10]}"


def _month_path(config, ts):
    return _dir(config) / f'{ts[:7]}.jsonl'


def _existing(config, ts):
    path = _month_path(config, ts)
    if not path.exists():
        return [], set()
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
    return rows, {_signature(r) for r in rows}


def transactions(config, month=None):
    ts = f'{month}-01' if month else datetime.now(timezone.utc).isoformat()
    return _existing(config, ts)[0]


def label_categories(config):
    return sorted({r.get('category', '') for r in _autolabel(config) if r.get('category')})


def set_category(config, tx_id, category):
    for path in sorted(_dir(config).glob('*.jsonl'), reverse=True):
        rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        if not any(r.get('id') == tx_id for r in rows):
            continue
        for r in rows:
            if r.get('id') == tx_id:
                r['category_override'] = category
                r['category_source'] = 'manual' if category else r.get('category_source', '')
        path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')
        return True
    return False


def ingest(config, entry):
    text = _text_of(entry.get('payload'))
    parsed = parse_text(text, _patterns(config))
    if not parsed or parsed['amount'] is None:
        if looks_like_transaction(text):
            messaging.send(config, 'notifications', 'Unparsed transaction — add a pattern:\n\n' + text)
        return None
    ts = entry.get('received_at') or datetime.now(timezone.utc).isoformat()
    category = _auto_category(parsed, _autolabel(config))
    tx = {
        'id': hashlib.sha1(f"{ts}|{text}".encode()).hexdigest()[:12],
        'ts': ts,
        'source': entry.get('source', ''),
        'account': _account(parsed, _cards(config)),
        'last4': parsed.get('last4'),
        'type': parsed['type'],
        'amount': parsed['amount'],
        'currency': parsed['currency'],
        'venue': parsed['venue'],
        'remaining': parsed['remaining'],
        'category': category,
        'category_source': 'auto' if category else '',
        'category_override': '',
        'pattern': parsed['pattern'],
        'raw_ref': entry.get('received_at', ''),
    }
    _, seen = _existing(config, ts)
    if _signature(tx) in seen:
        return None
    path = _month_path(config, ts)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(tx, ensure_ascii=False) + '\n')
    return tx
