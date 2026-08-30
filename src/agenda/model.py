from datetime import date, timedelta
from typing import ClassVar

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
    done_weeks: list[str] = []
