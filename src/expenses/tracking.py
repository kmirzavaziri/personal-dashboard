from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from expenses.budget import MISC, BudgetLine, Frequency
from transactions.ledger import Entry, Ledger
from transactions.rules import Period

_UNASSIGNED = 'Not assigned to a sub-category'


@dataclass(frozen=True)
class Piece:
    entry: Entry
    amount: float
    line: BudgetLine | None
    category: str

    @property
    def at(self) -> datetime:
        return self.entry.tx.at


@dataclass(frozen=True)
class Cell:
    label: str
    title: str
    spent: float
    allowance: float
    current: bool

    @property
    def ratio(self) -> float:
        return self.spent / self.allowance if self.allowance else (1.0 if self.spent else 0.0)


@dataclass
class LineStatus:
    key: str
    name: str
    line: BudgetLine | None
    budget: float
    spent: float
    expected: float
    state: str
    last_paid: datetime | None = None
    next_due: datetime | None = None
    today_spent: float = 0.0
    today_allowance: float = 0.0
    week_spent: float = 0.0
    week_allowance: float = 0.0
    days: list[tuple[date, float]] = field(default_factory=list)
    history: list[Cell] = field(default_factory=list)
    overdue: bool = False

    @property
    def frequency(self) -> Frequency | None:
        return self.line.frequency if self.line else None

    @property
    def ahead(self) -> float:
        return self.spent - self.expected


@dataclass
class CategoryStatus:
    key: str
    name: str
    lines: list[LineStatus]

    @property
    def budget(self) -> float:
        return sum(line.budget for line in self.lines)

    @property
    def spent(self) -> float:
        return sum(line.spent for line in self.lines)

    @property
    def expected(self) -> float:
        return sum(line.expected for line in self.lines)

    @property
    def state(self) -> str:
        return _paced_state(self.spent, self.budget, self.expected)


@dataclass
class Overview:
    period: Period
    categories: list[CategoryStatus]

    @property
    def budget(self) -> float:
        return sum(category.budget for category in self.categories)

    @property
    def spent(self) -> float:
        return sum(category.spent for category in self.categories)

    @property
    def expected(self) -> float:
        return sum(category.expected for category in self.categories)

    @property
    def lines(self) -> list[LineStatus]:
        return [line for category in self.categories for line in category.lines]

    @property
    def paced(self) -> list[LineStatus]:
        return [line for line in self.lines if line.line and line.line.paced]

    @property
    def bills(self) -> list[LineStatus]:
        return [line for line in self.lines if line.line and line.line.bill and line.budget]

    @property
    def unassigned(self) -> float:
        return sum(line.spent for line in self.lines if line.line is None)

    @property
    def daily_left(self) -> float:
        daily = [line for line in self.lines if line.line and line.line.paced]
        days_left = max(self.period.length_days - self.period.elapsed_days + 1, 1)
        return max(sum(line.budget - line.spent for line in daily), 0.0) / days_left


class Tracker:
    def __init__(self, ledger: Ledger, lines: list[BudgetLine], category_names: dict[str, str]):
        self.ledger = ledger
        self.lines = lines
        self.by_key = {line.key: line for line in lines}
        self.names = category_names
        self.budgeted = {line.category for line in lines}
        self.pieces = [piece for entry in ledger.visible if entry.counts_as_spending for piece in self._pieces(entry)]
        self.by_line: dict[str, list[Piece]] = {}
        for piece in self.pieces:
            if piece.line:
                self.by_line.setdefault(piece.line.key, []).append(piece)

    def overview(self, period: Period) -> Overview:
        now = min(period.now, period.end)
        in_period = [piece for piece in self.pieces if period.start <= piece.at < period.end]
        categories = []
        for key in dict.fromkeys([line.category for line in self.lines] + [piece.category for piece in in_period]):
            lines = [self._line_status(line, period, now, in_period) for line in self.lines if line.category == key]
            unassigned = [piece for piece in in_period if piece.category == key and piece.line is None]
            if unassigned:
                lines.append(LineStatus(key=f'{key or "misc"}-unassigned', name=_UNASSIGNED, line=None, budget=0.0,
                                        spent=sum(piece.amount for piece in unassigned), expected=0.0, state='unassigned'))
            categories.append(CategoryStatus(key=key or 'misc', name=self.names.get(key, 'Misc.'), lines=lines))
        categories.sort(key=lambda category: (category.key == 'misc', -category.budget))
        return Overview(period=period, categories=categories)

    def _pieces(self, entry: Entry) -> list[Piece]:
        scale = entry.aed / entry.tx.aed if entry.tx.aed else 1.0
        category = entry.category.key if entry.category and entry.category.key in self.budgeted else MISC
        pieces = []
        for amount, key in entry.tx.portions():
            line = self.by_key.get(key) or self._auto_line(entry, category)
            pieces.append(Piece(entry=entry, amount=amount * scale, line=line, category=line.category if line else category))
        return pieces

    def _auto_line(self, entry: Entry, category: str) -> BudgetLine | None:
        own = [line for line in self.lines if line.category == category]
        text = f'{entry.note} {entry.tx.description}'
        matched = next((line for line in own if line.claims(text)), None)
        if matched:
            return matched
        unmatched = [line for line in own if not line.match]
        return unmatched[0] if len(unmatched) == 1 else None

    def _line_status(self, line: BudgetLine, period: Period, now: datetime, in_period: list[Piece]) -> LineStatus:
        own = [piece for piece in in_period if piece.line is line]
        spent = sum(piece.amount for piece in own)
        history = [piece.at for piece in self.pieces if piece.line is line]
        last_paid = max(history, default=None)
        status = LineStatus(key=line.key, name=line.name, line=line, budget=0.0, spent=spent, expected=0.0, state='',
                            last_paid=last_paid)
        if line.paced:
            self._pace(status, line, period, now, own)
        elif line.bill:
            self._bill(status, line, period, history)
            status.overdue = status.state == 'due' and status.next_due is not None and status.next_due < now
        else:
            status.budget = status.expected = line.monthly
            status.state = 'over' if status.spent > status.budget + 1 else 'within'
        status.history = self._history(line, period, now)
        return status

    def _history(self, line: BudgetLine, period: Period, now: datetime) -> list[Cell]:
        clock = self.ledger.clock
        pieces = self.by_line.get(line.key, [])
        spent = lambda start, end: sum(piece.amount for piece in pieces if start <= piece.at < end)
        if line.frequency in (Frequency.DAILY, Frequency.WORKDAY):
            today = _day(clock, now)
            cells = []
            for back in range(6, -1, -1):
                day = today - timedelta(days=back)
                start = _day_start(clock, day)
                cells.append(Cell(label=day.strftime('%a'), title=day.strftime('%a %b %-d'),
                                  spent=spent(start, start + timedelta(days=1)),
                                  allowance=self._allowance_on(line, day, period), current=back == 0))
            return cells
        if line.frequency in (Frequency.WEEKLY, Frequency.BIWEEKLY):
            monday = _day(clock, now) - timedelta(days=_day(clock, now).weekday())
            weekly = line.cost_aed * line.times / (2 if line.frequency is Frequency.BIWEEKLY else 1)
            cells = []
            for back in range(5, -1, -1):
                first = monday - timedelta(weeks=back)
                start = _day_start(clock, first)
                cells.append(Cell(label=first.strftime('%b %-d'), title=f'Week of {first:%b %-d}',
                                  spent=spent(start, start + timedelta(weeks=1)), allowance=weekly, current=back == 0))
            return cells
        cycle = line.frequency.cycle_months
        periods = [period]
        while len(periods) < 6 * cycle:
            periods.append(self.ledger.previous(periods[-1]))
        periods.reverse()
        anchor = self._anchor(line, periods, cycle)
        windows = [periods[first:first + cycle] for first in range(anchor % cycle, len(periods), cycle)]
        cells = []
        for window in windows[-(6 if cycle == 1 else 4):]:
            start, end = window[0].start, window[-1].end
            label = window[-1].last_day.strftime('%b') if cycle == 1 else f'{window[0].last_day:%b %y} – {window[-1].last_day:%b %y}'
            allowance = line.monthly * cycle if line.paced else line.cost_aed * line.times
            cells.append(Cell(label=label, title=f'{window[0].start:%b %-d} – {window[-1].last_day:%b %-d}',
                              spent=spent(start, end), allowance=allowance, current=start <= now < end or window[-1] is period))
        return cells

    def _anchor(self, line: BudgetLine, periods: list[Period], cycle: int) -> int:
        if cycle == 1:
            return 0
        pieces = self.by_line.get(line.key, [])
        paid = [index for index, candidate in enumerate(periods)
                if any(candidate.start <= piece.at < candidate.end for piece in pieces)]
        return paid[-1] if paid else len(periods) - 1

    def _pace(self, status: LineStatus, line: BudgetLine, period: Period, now: datetime, own: list[Piece]) -> None:
        clock = self.ledger.clock
        status.budget = line.monthly
        status.expected = line.monthly * self._elapsed_share(line, period, now)
        status.state = _paced_state(status.spent, status.budget, status.expected)
        today = _day(clock, now)
        by_day: dict[date, float] = {}
        for piece in own:
            by_day[_day(clock, piece.at)] = by_day.get(_day(clock, piece.at), 0.0) + piece.amount
        status.today_spent = by_day.get(today, 0.0)
        status.today_allowance = self._allowance_on(line, today, period)
        week_start = today - timedelta(days=today.weekday())
        status.week_spent = sum(amount for day, amount in by_day.items() if week_start <= day <= today)
        status.week_allowance = sum(self._allowance_on(line, week_start + timedelta(days=offset), period) for offset in range(7))
        status.days = [(today - timedelta(days=back), by_day.get(today - timedelta(days=back), 0.0)) for back in range(6, -1, -1)]

    def _bill(self, status: LineStatus, line: BudgetLine, period: Period, history: list[datetime]) -> None:
        cost = line.cost_aed * line.times
        before = max((at for at in history if at < period.start), default=None)
        due = line.frequency.cycle_months == 1 or before is None or _add_months(before, line.frequency.cycle_months) < period.end
        status.budget = cost if due or status.spent else 0.0
        status.expected = status.budget
        if status.last_paid:
            status.next_due = _add_months(status.last_paid, line.frequency.cycle_months)
        if not status.budget:
            status.state = 'not due'
        elif status.spent > status.budget + 1:
            status.state = 'over'
        elif status.spent >= status.budget * 0.95:
            status.state = 'paid'
        elif status.spent:
            status.state = 'part paid'
        else:
            status.state = 'due'

    def _elapsed_share(self, line: BudgetLine, period: Period, now: datetime) -> float:
        if line.frequency is not Frequency.WORKDAY:
            return period.fraction
        days = [period.start.date() + timedelta(days=offset) for offset in range(period.length_days)]
        workdays = [day for day in days if self._is_workday(day)]
        done = [day for day in workdays if day <= _day(self.ledger.clock, now)]
        return len(done) / len(workdays) if workdays else period.fraction

    def _allowance_on(self, line: BudgetLine, day: date, period: Period) -> float:
        per = line.cost_aed * line.times
        if line.frequency is Frequency.DAILY:
            return per
        if line.frequency is Frequency.WORKDAY:
            return per if self._is_workday(day) else 0.0
        if line.frequency is Frequency.WEEKLY:
            return per / 7
        if line.frequency is Frequency.BIWEEKLY:
            return per / 14
        return line.monthly / period.length_days

    def _is_workday(self, day: date) -> bool:
        return day.strftime('%a').lower() not in self.ledger.clock.weekend


def _paced_state(spent: float, budget: float, expected: float) -> str:
    if spent > budget + 1:
        return 'over'
    if spent > expected + 1:
        return 'ahead'
    return 'on pace'


def _day(clock, at: datetime) -> date:
    return (clock.local(at) - timedelta(hours=clock.day_starts_at)).date()


def _day_start(clock, day: date) -> datetime:
    return datetime(day.year, day.month, day.day, clock.day_starts_at, tzinfo=ZoneInfo(clock.timezone))


def _add_months(at: datetime, months: int) -> datetime:
    index = at.year * 12 + at.month - 1 + months
    year, month = divmod(index, 12)
    for day in range(at.day, 0, -1):
        try:
            return at.replace(year=year, month=month + 1, day=day)
        except ValueError:
            continue
    return at
