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
    start: datetime
    end: datetime
    now: datetime

    @property
    def length_days(self) -> int:
        return (self.end - self.start).days

    @property
    def elapsed_days(self) -> int:
        return (self.now - self.start).days + 1

    @property
    def fraction(self) -> float:
        return self.elapsed_days / self.length_days

    def day(self, number: int) -> datetime:
        return self.start + timedelta(days=number - 1)

    @property
    def label(self) -> str:
        return f'{self.start:%b %-d} – {self.day(self.length_days):%b %-d} · day {self.elapsed_days} of {self.length_days}'


class Slot(BaseModel):
    model_config = ConfigDict(extra='forbid')

    key: str
    label: str
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


class Clock(BaseModel):
    model_config = ConfigDict(extra='forbid')

    timezone: str
    day_starts_at: int
    period_starts_on: int
    weekend: list[str]
    slots: list[Slot]

    @classmethod
    def load(cls, db) -> 'Clock':
        return cls.model_validate(read_yaml(db / 'transactions' / 'time.yaml'))

    def local(self, at: datetime) -> datetime:
        return at.astimezone(ZoneInfo(self.timezone))

    def period(self, at: datetime) -> 'Period':
        local = self.local(at)
        start = self._period_start(local.year, local.month, local.tzinfo)
        if local < start:
            start = self._period_start(*_shift_month(local.year, local.month, -1), local.tzinfo)
        return Period(start, self._period_start(*_shift_month(start.year, start.month, 1), local.tzinfo), local)

    def _period_start(self, year: int, month: int, tz) -> datetime:
        return datetime(year, month, min(self.period_starts_on, monthrange(year, month)[1]), tzinfo=tz)

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


class Rule(BaseModel):
    model_config = ConfigDict(extra='forbid')

    match: str
    slot: str = ''
    note: str = ''
    type: str = ''

    @property
    def is_pattern(self) -> bool:
        return self.match.startswith('re:')

    @property
    def precedence(self) -> tuple[bool, bool]:
        return bool(self.slot), not self.is_pattern

    def matches(self, haystack: str, slots_now: set[str]) -> bool:
        if self.slot and self.slot not in slots_now:
            return False
        if self.is_pattern:
            return re.search(self.match[3:], haystack, re.I) is not None
        return self.match.casefold() in haystack.casefold()


class Category(Model):
    SUBDIR = 'transactions/categories'

    key: str
    name: str
    rules: list[Rule] = []


def slug(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', name.casefold()).strip('_')
