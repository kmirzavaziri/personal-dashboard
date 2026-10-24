import json
import re
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

_LOCATION_SUFFIX = re.compile(r',[^,]*$')
UNCATEGORIZED = '-'


class Transaction(BaseModel):
    model_config = ConfigDict(extra='ignore')

    id: str
    ts: str
    source: str = ''
    account: str
    last4: str | None = None
    type: str
    amount: float
    currency: str | None = None
    amount_aed: float | None = None
    fx_rate: float | None = None
    venue: str = ''
    remaining: float | None = None
    pattern: str = ''
    raw_ref: str = ''
    category_override: str = ''
    note: str = ''

    @property
    def at(self) -> datetime:
        return datetime.fromisoformat(self.ts)

    @property
    def aed(self) -> float:
        return self.amount_aed if self.amount_aed is not None else self.amount

    @property
    def vendor(self) -> str:
        return ' '.join(_LOCATION_SUFFIX.sub('', self.venue).split())

    @property
    def signature(self) -> str:
        return f'{self.last4 or self.account}|{self.amount:.2f}|{self.ts[:10]}|{self.remaining}'

    @property
    def rule_haystack(self) -> str:
        return f'{self.venue} {self.type}'


class TransactionStore:
    def __init__(self, directory: Path):
        self.directory = directory

    def month_path(self, month: str) -> Path:
        return self.directory / f'{month}.jsonl'

    def read_month(self, month: str) -> list[Transaction]:
        path = self.month_path(month)
        if not path.exists():
            return []
        return [Transaction.model_validate_json(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]

    def write_month(self, month: str, rows: list[Transaction]) -> None:
        self.month_path(month).write_text(''.join(row.model_dump_json() + '\n' for row in rows), encoding='utf-8')

    def append(self, tx: Transaction) -> None:
        path = self.month_path(tx.ts[:7])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as f:
            f.write(tx.model_dump_json() + '\n')

    def months(self) -> list[str]:
        return sorted(path.stem for path in self.directory.glob('*.jsonl'))

    def all(self) -> list[Transaction]:
        return [tx for month in self.months() for tx in self.read_month(month)]

    def update_each(self, change) -> int:
        changed = 0
        for month in self.months():
            rows = self.read_month(month)
            hits = sum(1 for row in rows if change(row))
            if hits:
                self.write_month(month, rows)
                changed += hits
        return changed

    def update(self, tx_id: str, **fields) -> bool:
        for month in reversed(self.months()):
            rows = self.read_month(month)
            row = next((r for r in rows if r.id == tx_id), None)
            if row is None:
                continue
            for name, value in fields.items():
                setattr(row, name, value)
            self.write_month(month, rows)
            return True
        return False

    def clear(self) -> None:
        for month in self.months():
            self.month_path(month).unlink()
