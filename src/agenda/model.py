from datetime import date, timedelta
from typing import ClassVar

from pydantic import model_validator

from pkg.model.base import Model

DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
DAY_LABELS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


def week_str(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f'{year}-W{week:02d}'


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def current_week() -> str:
    return week_str(date.today())


def week_offset(target: date) -> int:
    return (monday_of(target) - monday_of(date.today())).days // 7


class CalendarEntry(Model):
    SUBDIR: ClassVar[str] = 'calendar'

    key: str
    title: str = ''
    labels: list[str] = []
    notes: str = ''
    order: int = 0
    task_key: str = ''
    day: str = ''
    date: str = ''
    milestone: bool = False
    done_weeks: list[str] = []

    @property
    def recurring(self) -> bool:
        return bool(self.day)

    @property
    def needs_task(self) -> bool:
        return not self.recurring and not self.milestone

    @model_validator(mode='after')
    def _reject_orphan(self) -> 'CalendarEntry':
        if self.needs_task and not self.task_key:
            raise ValueError(
                f'{self.key}: a dated entry must link a task (task_key) or be marked a milestone; '
                'only recurring (day) entries may be task-less'
            )
        return self
