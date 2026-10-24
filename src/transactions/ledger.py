from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from functools import cached_property, lru_cache
from pathlib import Path

from pkg.model.io import read_yaml
from transactions.rules import Category, Clock, Rule
from transactions.transaction import Transaction, TransactionStore

_REFUND_WINDOW = timedelta(days=120)
_FX_REFUND_TOLERANCE = 0.05
_SELF_TRANSFER_WINDOW = timedelta(days=3)
_MOVEMENT_TYPES = {'transfer', 'income'}


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
    refunds: tuple[Transaction, ...] = ()
    self_transfer: bool = False

    @property
    def aed(self) -> float:
        return self.tx.aed + sum(refund.aed for refund in self.refunds)

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

    @property
    def labelable(self) -> bool:
        outgoing_transfer = self.type == 'transfer' and not self.self_transfer
        return (self.spend or outgoing_transfer) and not self.is_inflow

    @property
    def partially_refunded(self) -> bool:
        return bool(self.refunds) and abs(self.aed) > 0.005


class Ledger:
    def __init__(self, transactions: list[Transaction], categories: list[Category], clock: Clock,
                 types: dict[str, dict], cards: list[dict], owner: dict):
        self.categories = sorted(categories, key=lambda c: c.name.casefold())
        self._by_key = {c.key: c for c in self.categories}
        self.clock = clock
        self._types = types
        self._accounts = {card['last4']: card['display'] for card in cards if card.get('last4')}
        resolved = [self._resolve(tx) for tx in sorted(transactions, key=lambda t: t.at)]
        refunds = _refunds_by_purchase(resolved)
        self._hidden = {tx.id for txs in refunds.values() for tx in txs}
        own = _self_transfers(resolved, set(self._accounts.values()), owner)
        self.entries = [replace(entry, refunds=tuple(refunds.get(entry.tx.id, ())), self_transfer=entry.tx.id in own)
                        for entry in resolved]
        self._hidden |= {entry.tx.id for entry in self.entries if entry.refunds and not entry.partially_refunded}

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
        return [entry for entry in self.entries if entry.tx.id not in self._hidden]

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
            if entry.category or not entry.labelable or not vendor:
                continue
            row = totals.setdefault(vendor.casefold(), {'vendor': vendor, 'total': 0.0, 'count': 0, 'last': ''})
            row['total'] += entry.aed
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



def _within_window(refund: Entry, purchase: Entry) -> bool:
    return purchase.tx.at <= refund.tx.at and refund.tx.at - purchase.tx.at <= _REFUND_WINDOW


def _fully_refunds(refund: Entry, purchase: Entry) -> bool:
    if purchase.tx.currency == refund.tx.currency:
        return round(abs(purchase.tx.amount), 2) == round(abs(refund.tx.amount), 2)
    return abs(abs(purchase.tx.aed) - abs(refund.tx.aed)) <= abs(purchase.tx.aed) * _FX_REFUND_TOLERANCE


def _vendor_stem(vendor: str) -> str:
    first = vendor.split()[0] if vendor.split() else ''
    return ''.join(ch for ch in first.casefold() if ch.isalnum())


def _same_vendor(refund: Entry, purchase: Entry) -> bool:
    stem = _vendor_stem(refund.tx.vendor)
    return len(stem) >= 3 and _vendor_stem(purchase.tx.vendor).startswith(stem)


def _refunds_by_purchase(entries: list[Entry]) -> dict[str, list[Transaction]]:
    open_purchases: dict[str, list[Entry]] = defaultdict(list)
    remaining: dict[str, float] = {}
    refunds: dict[str, list[Transaction]] = defaultdict(list)
    for entry in entries:
        if entry.type != 'refund':
            if entry.spend and entry.tx.amount > 0:
                open_purchases[entry.account].append(entry)
                remaining[entry.tx.id] = entry.tx.aed
            continue
        candidates = [p for p in open_purchases[entry.account] if _within_window(entry, p)]
        full = [p for p in candidates if _fully_refunds(entry, p)]
        partial = [p for p in candidates if _same_vendor(entry, p) and remaining[p.tx.id] > abs(entry.tx.aed)]
        preferred = [p for p in full if _same_vendor(entry, p)] or full or partial
        if not preferred:
            continue
        purchase = preferred[-1]
        refunds[purchase.tx.id].append(entry.tx)
        remaining[purchase.tx.id] -= abs(entry.tx.aed)
        if purchase in full:
            open_purchases[entry.account].remove(purchase)
    return refunds


def _self_transfers(entries: list[Entry], own_accounts: set[str], owner: dict) -> set[str]:
    markers = [text.casefold() for text in (owner.get('names') or []) + (owner.get('movements') or [])]
    to_owner = {e.tx.id for e in entries
                if e.type in _MOVEMENT_TYPES and any(marker in e.tx.venue.casefold() for marker in markers)}
    outgoing = [e for e in entries if e.type == 'transfer' and e.tx.amount > 0 and e.account in own_accounts]
    incoming = [e for e in entries if e.type in _MOVEMENT_TYPES and e.tx.amount < 0 and e.account in own_accounts]
    paired: set[str] = set()
    for out in outgoing:
        match = next((inc for inc in incoming
                      if inc.tx.id not in paired and inc.account != out.account
                      and round(abs(inc.tx.aed), 2) == round(out.tx.aed, 2)
                      and abs(inc.tx.at - out.tx.at) <= _SELF_TRANSFER_WINDOW), None)
        if match is not None:
            paired |= {out.tx.id, match.tx.id}
    return paired | to_owner


def _fingerprint(directory: Path) -> tuple:
    return tuple((path.name, stat.st_mtime_ns, stat.st_size)
                 for path in sorted(directory.rglob('*')) if path.is_file() and (stat := path.stat()))


@lru_cache(maxsize=2)
def _load(db: Path, fingerprint: tuple) -> Ledger:
    types = {t['key']: t for t in read_yaml(db / 'transactions' / 'types.yaml') or []}
    cards = read_yaml(db / 'transactions' / 'cards.yaml') or []
    owner = read_yaml(db / 'transactions' / 'owner.yaml') or {}
    return Ledger(TransactionStore(db / 'transactions').all(), Category.objects.all(), Clock.load(db), types, cards, owner)
