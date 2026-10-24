import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

from pkg.model.base import Model
from pkg.model.io import read_yaml

_WEEKDAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')


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
    weekend: list[str]
    slots: list[Slot]

    @classmethod
    def load(cls, db) -> 'Clock':
        return cls.model_validate(read_yaml(db / 'transactions' / 'time.yaml'))

    def local(self, at: datetime) -> datetime:
        return at.astimezone(ZoneInfo(self.timezone))

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
