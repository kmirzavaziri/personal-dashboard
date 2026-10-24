from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from functools import cached_property, lru_cache
from pathlib import Path

from pkg.model.io import read_yaml
from transactions.rules import Category, Clock, Rule
from transactions.transaction import Transaction, TransactionStore

_REFUND_WINDOW = timedelta(days=120)


@dataclass(frozen=True)
class Match:
    category: Category
    rule: Rule
    index: int


@dataclass(frozen=True)
class Entry:
    tx: Transaction
    account: str
    category: Category | None
    match: Match | None
    type: str
    spend: bool
    refund: Transaction | None = None

    @property
    def note(self) -> str:
        return self.tx.note or (self.match.rule.note if self.match else '')

    @property
    def default_note(self) -> str:
        return self.match.rule.note if self.match else ''

    @property
    def category_name(self) -> str:
        return self.category.name if self.category else ''

    @property
    def is_inflow(self) -> bool:
        return self.tx.aed < 0


class Ledger:
    def __init__(self, transactions: list[Transaction], categories: list[Category], clock: Clock,
                 types: dict[str, dict], cards: list[dict]):
        self.categories = sorted(categories, key=lambda c: c.name.casefold())
        self._by_key = {c.key: c for c in self.categories}
        self.clock = clock
        self._types = types
        self._accounts = {card['last4']: card['display'] for card in cards if card.get('last4')}
        resolved = [self._resolve(tx) for tx in sorted(transactions, key=lambda t: t.at)]
        self._pairs = self._refund_pairs(resolved)
        by_id = {entry.tx.id: entry.tx for entry in resolved}
        self.entries = [self._with_refund(entry, by_id) for entry in resolved]

    @classmethod
    def load(cls, config) -> 'Ledger':
        return _load(config.db, _fingerprint(config.db / 'transactions'))

    def counts_as_spend(self, type_key: str) -> bool:
        kind = self._types.get(type_key)
        if kind is None:
            raise ValueError(f'transaction type {type_key!r} is missing from transactions/types.yaml')
        return bool(kind.get('spend'))

    @cached_property
    def visible(self) -> list[Entry]:
        hidden = set(self._pairs) | set(self._pairs.values())
        return [entry for entry in self.entries if entry.tx.id not in hidden]

    @property
    def earliest(self) -> datetime | None:
        return self.entries[0].tx.at if self.entries else None

    def between(self, start: datetime, end: datetime) -> list[Entry]:
        return [entry for entry in self.visible if start <= entry.tx.at < end]

    def rule_hits(self) -> Counter:
        return Counter((e.match.category.key, e.match.index) for e in self.visible if e.match and not e.tx.category_override)

    def uncategorized_vendors(self) -> list[dict]:
        totals: dict[str, dict] = {}
        for entry in self.visible:
            vendor = entry.tx.vendor
            if entry.category or not entry.spend or not vendor:
                continue
            row = totals.setdefault(vendor.casefold(), {'vendor': vendor, 'total': 0.0, 'count': 0, 'last': ''})
            row['total'] += entry.tx.aed
            row['count'] += 1
            row['last'] = max(row['last'], entry.tx.ts[:10])
        return sorted(totals.values(), key=lambda row: -row['total'])

    def _match(self, tx: Transaction) -> Match | None:
        slots_now = self.clock.slot_keys_at(tx.at)
        candidates = [
            Match(category, rule, index)
            for category in self.categories
            for index, rule in enumerate(category.rules)
            if rule.matches(tx.rule_haystack, slots_now)
        ]
        return max(candidates, key=lambda m: m.rule.precedence, default=None)

    def _resolve(self, tx: Transaction) -> Entry:
        if tx.category_override:
            category, match = self._by_key.get(tx.category_override), None
        else:
            match = self._match(tx)
            category = match.category if match else None
        kind = (match.rule.type if match else '') or tx.type
        account = self._accounts.get(tx.last4 or '', tx.account)
        return Entry(tx=tx, account=account, category=category, match=match, type=kind, spend=self.counts_as_spend(kind))

    @staticmethod
    def _refund_pairs(entries: list[Entry]) -> dict[str, str]:
        open_purchases: dict[tuple, list[Entry]] = defaultdict(list)
        pairs: dict[str, str] = {}
        for entry in entries:
            key = (entry.account, entry.tx.currency, round(abs(entry.tx.amount), 2))
            if entry.type == 'refund':
                candidates = [p for p in open_purchases[key] if entry.tx.at - p.tx.at <= _REFUND_WINDOW]
                same_vendor = [p for p in candidates if p.tx.vendor.casefold() == entry.tx.vendor.casefold()]
                purchase = (same_vendor or candidates or [None])[-1]
                if purchase is not None:
                    open_purchases[key].remove(purchase)
                    pairs[purchase.tx.id] = entry.tx.id
            elif entry.spend and entry.tx.amount > 0:
                open_purchases[key].append(entry)
        return pairs

    def _with_refund(self, entry: Entry, by_id: dict[str, Transaction]) -> Entry:
        refund_id = self._pairs.get(entry.tx.id)
        return replace(entry, refund=by_id[refund_id]) if refund_id else entry


def _fingerprint(directory: Path) -> tuple:
    return tuple((path.name, stat.st_mtime_ns, stat.st_size)
                 for path in sorted(directory.rglob('*')) if path.is_file() and (stat := path.stat()))


@lru_cache(maxsize=2)
def _load(db: Path, fingerprint: tuple) -> Ledger:
    types = {t['key']: t for t in read_yaml(db / 'transactions' / 'types.yaml') or []}
    cards = read_yaml(db / 'transactions' / 'cards.yaml') or []
    return Ledger(TransactionStore(db / 'transactions').all(), Category.objects.all(), Clock.load(db), types, cards)
