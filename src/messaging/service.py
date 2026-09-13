import json
import re
import urllib.request
from datetime import datetime, timezone
from urllib.error import URLError

from pkg.model.io import read_yaml

_TELEGRAM_API = 'https://api.telegram.org/bot{token}/sendMessage'


def _inbox_dir(config):
    return config.db / 'messaging' / 'inbox'


def _config(config) -> dict:
    return read_yaml(config.db / 'messaging' / 'config.yaml') or {}


def _text_of(payload) -> str:
    return payload.get('text', '') if isinstance(payload, dict) else str(payload)


def record(config, source: str, payload) -> dict:
    entry = {'received_at': datetime.now(timezone.utc).isoformat(), 'source': source, 'payload': payload}
    path = _inbox_dir(config) / f'{datetime.now(timezone.utc):%Y-%m}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    return entry


def inbox(config, month: str | None = None) -> list[dict]:
    path = _inbox_dir(config) / f'{month or datetime.now(timezone.utc):%Y-%m}.jsonl'
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def send(config, channel: str, text: str) -> bool:
    token = config.telegram_bot_token
    chat_id = (_config(config).get('channels') or {}).get(channel, channel)
    if not token or not chat_id:
        return False
    body = json.dumps({'chat_id': chat_id, 'text': text}).encode()
    req = urllib.request.Request(_TELEGRAM_API.format(token=token), data=body,
                                 headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except URLError:
        return False


def _matches(match: str, text: str) -> bool:
    if not match:
        return True
    if match.startswith('re:'):
        return re.search(match[3:], text) is not None
    return match.lower() in text.lower()


def relay(config, text: str) -> list[str]:
    sent = []
    for rule in _config(config).get('relay') or []:
        if rule.get('to') and _matches(rule.get('match', ''), text) and send(config, rule['to'], text):
            sent.append(rule['to'])
    return sent


def ingest(config, source: str, payload) -> dict:
    entry = record(config, source, payload)
    try:
        relay(config, _text_of(payload))
    except Exception:
        pass
    return entry
