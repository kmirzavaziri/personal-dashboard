import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from pkg.model.base import Model
from pkg.model.io import read_yaml

_WEEKDAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + month - 1 + delta
    return index // 12, index % 12 + 1


@dataclass(frozen=True)
class Period:
    key: str
    start: datetime
    end: datetime
    now: datetime

    @property
    def last_day(self) -> datetime:
        return self.end - timedelta(seconds=1)

    @property
    def length_days(self) -> int:
        return (self.last_day.date() - self.start.date()).days + 1

    @property
    def elapsed_days(self) -> int:
        return max(1, min((self.now.date() - self.start.date()).days + 1, self.length_days))

    @property
    def fraction(self) -> float:
        return self.elapsed_days / self.length_days

    def day(self, number: int) -> datetime:
        return self.start + timedelta(days=number - 1)

    @property
    def name(self) -> str:
        return f'{self.last_day:%B %Y}'

    @property
    def range_label(self) -> str:
        return f'{self.start:%b %-d} – {self.last_day:%b %-d}'

    @property
    def label(self) -> str:
        return f'{self.range_label} · day {self.elapsed_days} of {self.length_days}'


class Window(BaseModel):
    model_config = ConfigDict(extra='forbid')

    days: str
    start: int | None = None
    end: int | None = None

    def contains(self, day: str, hour: int, weekend: list[str]) -> bool:
        if (day in weekend) != (self.days == 'weekend'):
            return False
        if self.start is None or self.end is None:
            return True
        if self.start < self.end:
            return self.start <= hour < self.end
        return hour >= self.start or hour < self.end


class Slot(BaseModel):
    model_config = ConfigDict(extra='forbid')

    key: str
    label: str
    short: str
    windows: list[Window]

    def contains(self, day: str, hour: int, weekend: list[str]) -> bool:
        return any(window.contains(day, hour, weekend) for window in self.windows)


class Clock(BaseModel):
    model_config = ConfigDict(extra='forbid')

    timezone: str
    day_starts_at: int
    period_starts_on: int
    period_marker: str
    period_marker_window_days: int
    weekend: list[str]
    slots: list[Slot]

    @classmethod
    def load(cls, db) -> 'Clock':
        return cls.model_validate(read_yaml(db / 'transactions' / 'time.yaml'))

    def local(self, at: datetime) -> datetime:
        return at.astimezone(ZoneInfo(self.timezone))

    def default_period_start(self, year: int, month: int) -> datetime:
        return datetime(year, month, min(self.period_starts_on, monthrange(year, month)[1]), tzinfo=ZoneInfo(self.timezone))

    def month(self, month: str) -> tuple[datetime, datetime]:
        year, number = map(int, month.split('-'))
        tz = ZoneInfo(self.timezone)
        return datetime(year, number, 1, tzinfo=tz), datetime(*_shift_month(year, number, 1), 1, tzinfo=tz)

    def slot_keys_at(self, at: datetime) -> set[str]:
        local = self.local(at)
        day = _WEEKDAYS[(local - timedelta(hours=self.day_starts_at)).weekday()]
        return {slot.key for slot in self.slots if slot.contains(day, local.hour, self.weekend)}

    def slot(self, key: str) -> Slot | None:
        return next((slot for slot in self.slots if slot.key == key), None)


class Matching(BaseModel):
    model_config = ConfigDict(extra='forbid')

    same_movement_hours: int
    charges_aed: float
    self_transfer_days: int
    settlement_days: int
    refund_days: int
    fx_refund_ratio: float
    statement_days: int
    generic_descriptions: list[str]
    clearing_accounts: list[str] = []

    @classmethod
    def load(cls, db) -> 'Matching':
        return cls.model_validate(read_yaml(db / 'transactions' / 'matching.yaml'))

    @property
    def same_movement(self) -> timedelta:
        return timedelta(hours=self.same_movement_hours)

    @property
    def self_transfer(self) -> timedelta:
        return timedelta(days=self.self_transfer_days)

    @property
    def settlement(self) -> timedelta:
        return timedelta(days=self.settlement_days)

    @property
    def refund(self) -> timedelta:
        return timedelta(days=self.refund_days)

    def is_generic(self, description: str) -> bool:
        return description.casefold() in {generic.casefold() for generic in self.generic_descriptions}


class Rule(BaseModel):
    model_config = ConfigDict(extra='forbid')

    match: str
    slots: list[str] = []
    note: str = ''
    type: str = ''

    @property
    def precedence(self) -> bool:
        return bool(self.slots)

    def matches(self, vendor: str, type_key: str, slots_now: set[str]) -> bool:
        if self.slots and not slots_now.intersection(self.slots):
            return False
        return self.match.casefold() in (vendor.casefold(), type_key.casefold())


class Category(Model):
    SUBDIR = 'transactions/categories'

    key: str
    name: str
    rules: list[Rule] = []


def slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', name.casefold()).strip('_')
