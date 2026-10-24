import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

CHAT_DB = Path.home() / 'Library' / 'Messages' / 'chat.db'
CHAT_DB_WAL = CHAT_DB.with_name('chat.db-wal')
IPHONE_BACKUPS = Path.home() / 'Library' / 'Application Support' / 'MobileSync' / 'Backup'
_IPHONE_SMS_DB_FILE = '3d/3d0d7e5fb2ce288813306e4d4636395e047a3d28'
_APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
_TYPEDSTREAM_INT16 = 0x81
_TYPEDSTREAM_INT32 = 0x82


@dataclass(frozen=True)
class Message:
    row_id: int
    sender: str
    text: str
    sent_at: datetime

    def as_payload(self) -> dict:
        return {'text': self.text, 'sender': self.sender, 'sent_at': self.sent_at.isoformat()}


def from_apple_time(nanoseconds: int) -> datetime:
    return _APPLE_EPOCH + timedelta(microseconds=nanoseconds // 1000)


def to_apple_time(at: datetime) -> int:
    return int((at - _APPLE_EPOCH).total_seconds()) * 1_000_000_000


def attributed_body_text(blob: bytes) -> str:
    marker = blob.find(b'NSString')
    start = blob.find(b'+', marker) if marker >= 0 else -1
    if start < 0:
        return ''
    cursor = start + 1
    length = blob[cursor]
    cursor += 1
    if length == _TYPEDSTREAM_INT16:
        length, cursor = int.from_bytes(blob[cursor:cursor + 2], 'little'), cursor + 2
    elif length == _TYPEDSTREAM_INT32:
        length, cursor = int.from_bytes(blob[cursor:cursor + 4], 'little'), cursor + 4
    return blob[cursor:cursor + length].decode('utf-8', 'replace')


def latest_iphone_backup() -> Path:
    candidates = [backup / _IPHONE_SMS_DB_FILE for backup in IPHONE_BACKUPS.glob('*')]
    existing = [path for path in candidates if path.exists()]
    if not existing:
        raise FileNotFoundError(f'no unencrypted iPhone backup with messages under {IPHONE_BACKUPS}')
    return max(existing, key=lambda path: path.stat().st_mtime)


def received(senders: list[str], after_row_id: int, since: datetime, database: Path = CHAT_DB) -> list[Message]:
    if not senders:
        return []
    placeholders = ','.join('?' * len(senders))
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
        rows = db.execute(
            f'SELECT message.ROWID, handle.id, message.text, message.attributedBody, message.date '
            f'FROM message JOIN handle ON message.handle_id = handle.ROWID '
            f'WHERE message.is_from_me = 0 AND message.ROWID > ? AND message.date >= ? '
            f'AND handle.id IN ({placeholders}) ORDER BY message.ROWID',
            (after_row_id, to_apple_time(since), *senders),
        ).fetchall()
    messages = (
        Message(row_id, sender, ' '.join((text or attributed_body_text(body or b'')).split()), from_apple_time(date))
        for row_id, sender, text, body, date in rows
    )
    return [message for message in messages if message.text]
