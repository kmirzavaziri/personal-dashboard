from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from functools import cached_property, lru_cache
from pathlib import Path

from pkg.model.io import read_yaml
from transactions.rules import Category, Clock, Matching, Period, Rule, _shift_month
from transactions.transaction import Transaction, TransactionStore

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
                 types: dict[str, dict], cards: list[dict], owner: dict, matching: Matching,
                 period_starts: dict[str, str]):
        self.categories = sorted(categories, key=lambda c: c.name.casefold())
        self._by_key = {c.key: c for c in self.categories}
        self.clock = clock
        self._types = types
        self._accounts = {card['last4']: card['display'] for card in cards if card.get('last4')}
        resolved = [self._resolve(tx) for tx in sorted(transactions, key=lambda t: t.at)]
        refunds = _refunds_by_purchase(resolved, matching)
        self._hidden = {tx.id for txs in refunds.values() for tx in txs}
        own = _self_transfers(resolved, set(self._accounts.values()), owner, matching.self_transfer)
        self.entries = [replace(entry, refunds=tuple(refunds.get(entry.tx.id, ())), self_transfer=entry.tx.id in own,
                                spend=entry.spend and entry.tx.id not in own)
                        for entry in resolved]
        self._hidden |= {entry.tx.id for entry in self.entries if entry.refunds and not entry.partially_refunded}
        self._boundaries = self._period_boundaries(period_starts)

    @classmethod
    def load(cls, config) -> 'Ledger':
        return _load(config.db, _fingerprint(config.db / 'transactions'))

    def counts_as_spend(self, type_key: str) -> bool:
        kind = self._types.get(type_key)
        if kind is None:
            raise ValueError(f'transaction type {type_key!r} is missing from transactions/types.yaml')
        return bool(kind.get('spend'))

    def period(self, at: datetime) -> Period:
        index = bisect_right([start for _, start in self._boundaries], at) - 1
        key, start = self._boundaries[max(index, 0)]
        end = self._boundaries[index + 1][1] if index + 1 < len(self._boundaries) else start + timedelta(days=31)
        return Period(key, start, end, self.clock.local(at))

    def following_key(self, key: str) -> str | None:
        keys = [k for k, _ in self._boundaries]
        index = keys.index(key) if key in keys else -1
        return keys[index + 1] if 0 <= index < len(keys) - 1 else None

    def entry_after(self, tx_id: str) -> Entry | None:
        ordered = self.visible
        index = next((i for i, entry in enumerate(ordered) if entry.tx.id == tx_id), None)
        return ordered[index + 1] if index is not None and index + 1 < len(ordered) else None

    def previous(self, period: Period) -> Period:
        return self.period(period.start - timedelta(seconds=1))

    def _period_boundaries(self, overrides: dict[str, str]) -> list[tuple[str, datetime]]:
        by_id = {entry.tx.id: entry for entry in self.entries}
        marker = self.clock.period_marker.casefold()
        window = timedelta(days=self.clock.period_marker_window_days)
        markers = [e for e in self.entries if marker and e.tx.vendor.casefold() == marker and e.is_inflow]
        now = self.clock.local(datetime.now().astimezone())
        first = self.entries[0].tx.at if self.entries else now
        year, month = _shift_month(first.year, first.month, -1)
        boundaries = []
        while (year, month) <= _shift_month(now.year, now.month, 2):
            key = f'{year}-{month:02d}'
            default = self.clock.default_period_start(year, month)
            override = by_id.get(overrides.get(key, ''))
            nearby = [e for e in markers if abs(e.tx.at - default) <= window]
            if override is not None:
                start = override.tx.at
            elif nearby:
                start = min(nearby, key=lambda e: abs(e.tx.at - default)).tx.at
            else:
                start = default
            boundaries.append((key, start))
            year, month = _shift_month(year, month, 1)
        return sorted(boundaries, key=lambda pair: pair[1])

    def category(self, key: str) -> Category | None:
        return self._by_key.get(key)

    @cached_property
    def visible(self) -> list[Entry]:
        return [entry for entry in self.entries if entry.tx.id not in self._hidden]

    @property
    def earliest(self) -> datetime | None:
        return self.entries[0].tx.at if self.entries else None

    def between(self, start: datetime, end: datetime) -> list[Entry]:
        return [entry for entry in self.visible if start <= entry.tx.at < end]

    def vendors(self) -> list[str]:
        counts = Counter(entry.tx.vendor for entry in self.visible if entry.tx.vendor)
        return [vendor for vendor, _ in counts.most_common()]

    def vendor_summaries(self) -> list[dict]:
        rows: dict[str, dict] = {}
        for entry in self.visible:
            vendor = entry.tx.vendor
            if not vendor or entry.self_transfer or entry.type == 'declined':
                continue
            row = rows.setdefault(vendor.casefold(), {'vendor': vendor, 'total': 0.0, 'count': 0, 'last': '',
                                                      'inflow': 0, 'categories': Counter()})
            row['total'] += entry.aed
            row['count'] += 1
            row['last'] = max(row['last'], entry.tx.ts[:10])
            row['inflow'] += entry.is_inflow
            row['categories'][entry.category.key if entry.category else ''] += 1
        return list(rows.values())

    def _match(self, tx: Transaction) -> Match | None:
        slots_now = self.clock.slot_keys_at(tx.at)
        candidates = [
            Match(category, rule, index)
            for category in self.categories
            for index, rule in enumerate(category.rules)
            if rule.matches(tx.vendor, tx.type, slots_now)
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



def _within_window(refund: Entry, purchase: Entry, window: timedelta) -> bool:
    return purchase.tx.at <= refund.tx.at and refund.tx.at - purchase.tx.at <= window


def _fully_refunds(refund: Entry, purchase: Entry, fx_ratio: float) -> bool:
    if purchase.tx.currency == refund.tx.currency:
        return round(abs(purchase.tx.amount), 2) == round(abs(refund.tx.amount), 2)
    return abs(abs(purchase.tx.aed) - abs(refund.tx.aed)) <= abs(purchase.tx.aed) * fx_ratio


def _vendor_stem(vendor: str) -> str:
    first = vendor.split()[0] if vendor.split() else ''
    return ''.join(ch for ch in first.casefold() if ch.isalnum())


def _same_vendor(refund: Entry, purchase: Entry) -> bool:
    stem = _vendor_stem(refund.tx.vendor)
    return len(stem) >= 3 and _vendor_stem(purchase.tx.vendor).startswith(stem)


def _refunds_by_purchase(entries: list[Entry], matching: Matching) -> dict[str, list[Transaction]]:
    open_purchases: dict[str, list[Entry]] = defaultdict(list)
    remaining: dict[str, float] = {}
    refunds: dict[str, list[Transaction]] = defaultdict(list)
    for entry in entries:
        if entry.type != 'refund':
            if entry.spend and entry.tx.amount > 0:
                open_purchases[entry.account].append(entry)
                remaining[entry.tx.id] = entry.tx.aed
            continue
        candidates = [p for p in open_purchases[entry.account] if _within_window(entry, p, matching.refund)]
        full = [p for p in candidates if _fully_refunds(entry, p, matching.fx_refund_ratio)]
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


def _pairs_with(out: Entry, inc: Entry, window: timedelta) -> bool:
    return (inc.account != out.account and round(abs(inc.tx.aed), 2) == round(out.tx.aed, 2)
            and abs(inc.tx.at - out.tx.at) <= window)


def _self_transfers(entries: list[Entry], own_accounts: set[str], owner: dict, window: timedelta) -> set[str]:
    markers = [text.casefold() for text in (owner.get('names') or []) + (owner.get('movements') or [])]
    to_owner = {e.tx.id for e in entries
                if e.type in _MOVEMENT_TYPES and any(marker in e.tx.description.casefold() for marker in markers)}
    outgoing = [e for e in entries if e.type == 'transfer' and e.tx.amount > 0 and e.account in own_accounts]
    incoming = [e for e in entries if e.type in _MOVEMENT_TYPES and e.tx.amount < 0 and e.account in own_accounts]
    candidates = {out.tx.id: [inc for inc in incoming if _pairs_with(out, inc, window)] for out in outgoing}
    paired: set[str] = set()
    for out in sorted(outgoing, key=lambda o: (len(candidates[o.tx.id]), o.tx.at)):
        match = min((inc for inc in candidates[out.tx.id] if inc.tx.id not in paired),
                    key=lambda inc: abs(inc.tx.at - out.tx.at), default=None)
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
    return Ledger(TransactionStore(db / 'transactions').all(), Category.objects.all(), Clock.load(db), types, cards, owner,
                  Matching.load(db), read_yaml(db / 'transactions' / 'period_starts.yaml') or {})
