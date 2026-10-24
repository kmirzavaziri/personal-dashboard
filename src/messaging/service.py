import json
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.error import URLError

from pkg.model.io import read_yaml

_TELEGRAM_API = 'https://api.telegram.org/bot{token}/sendMessage'
_DUPLICATE_WINDOW = timedelta(days=2)


def _inbox_dir(config):
    return config.db / 'messaging' / 'inbox'


def _config(config) -> dict:
    return read_yaml(config.db / 'messaging' / 'config.yaml') or {}


def relay_senders(config) -> list[str]:
    return list((_config(config).get('relay') or {}).get('senders') or [])


def text_of(payload) -> str:
    text = payload.get('text', '') if isinstance(payload, dict) else str(payload or '')
    return ' '.join(text.split())


def _sent_at(payload) -> datetime:
    sent = payload.get('sent_at') if isinstance(payload, dict) else None
    return datetime.fromisoformat(sent) if sent else datetime.now(timezone.utc)


def _month_path(config, at: datetime):
    return _inbox_dir(config) / f'{at:%Y-%m}.jsonl'


def _read(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def inbox(config, month: str | None = None) -> list[dict]:
    path = _inbox_dir(config) / f'{month or f"{datetime.now(timezone.utc):%Y-%m}"}.jsonl'
    return _read(path) if path.exists() else []


def all_entries(config) -> list[dict]:
    return [e for path in sorted(_inbox_dir(config).glob('*.jsonl')) for e in _read(path)]


def _neighbors(config, at: datetime) -> list[dict]:
    months = {f'{day:%Y-%m}' for day in (at - _DUPLICATE_WINDOW, at, at + _DUPLICATE_WINDOW)}
    return [entry for month in sorted(months) for entry in inbox(config, month)]


def _is_duplicate(config, text: str, at: datetime) -> bool:
    return any(
        text_of(entry.get('payload')) == text
        and abs(datetime.fromisoformat(entry['received_at']) - at) <= _DUPLICATE_WINDOW
        for entry in _neighbors(config, at)
    )


def ingest(config, source: str, payload) -> dict | None:
    at = _sent_at(payload)
    if _is_duplicate(config, text_of(payload), at):
        return None
    entry = {'received_at': at.isoformat(), 'source': source, 'payload': payload}
    path = _month_path(config, at)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    return entry


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
