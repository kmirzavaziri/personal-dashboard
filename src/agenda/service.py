import re
from datetime import date

from agenda.model import CalendarEntry, DAYS, current_week
from planner.model import Task


def slug(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:60] or 'entry'


def unique_key(base: str) -> str:
    key, suffix = base, 2
    while CalendarEntry.objects.get_or_none(key=key) is not None:
        key, suffix = f'{base}-{suffix}', suffix + 1
    return key


def next_order() -> int:
    return max((e.order for e in CalendarEntry.objects.all()), default=0) + 1


def flatten(labels) -> list[str]:
    values = labels if isinstance(labels, list) else ([labels] if labels else [])
    return [part.strip() for value in values for part in str(value).split(',') if part.strip()]


def get(key: str) -> CalendarEntry:
    entry = CalendarEntry.objects.get_or_none(key=key)
    if entry is None:
        raise ValueError(f'Entry not found: {key}')
    return entry


def add(title=None, day=None, on=None, task=None, labels=None, notes: str = '') -> CalendarEntry:
    if bool(day) == bool(on):
        raise ValueError('pass exactly one of day (weekday) or date (YYYY-MM-DD)')
    if day and day not in DAYS:
        raise ValueError(f"day must be one of {', '.join(DAYS)}")
    if on:
        date.fromisoformat(on)
    if task and Task.objects.get_or_none(key=task) is None:
        raise ValueError(f'No such task: {task}')
    if not title and not task:
        raise ValueError('provide a title, or task to pull it from')
    display = title or Task.objects.get(key=task).title
    entry = CalendarEntry(key=unique_key(slug(display)), title=title or '', task_key=task or '',
                          day=day or '', date=on or '', labels=flatten(labels), notes=notes, order=next_order())
    entry.save()
    return entry


def edit(key: str, title=None, day=None, on=None, task=None, labels=None, notes=None, order=None) -> CalendarEntry:
    entry = get(key)
    if title is not None:
        entry.title = title
    if day is not None:
        if day not in DAYS:
            raise ValueError(f"day must be one of {', '.join(DAYS)}")
        entry.day, entry.date = day, ''
    if on is not None:
        date.fromisoformat(on)
        entry.date, entry.day = on, ''
    if task is not None:
        if task and Task.objects.get_or_none(key=task) is None:
            raise ValueError(f'No such task: {task}')
        entry.task_key = task
    if labels is not None:
        entry.labels = flatten(labels)
    if notes is not None:
        entry.notes = notes
    if order is not None:
        entry.order = int(order)
    entry.save()
    return entry


def check(key: str, week=None) -> CalendarEntry:
    entry = get(key)
    if entry.day:
        target = week or current_week()
        if target not in entry.done_weeks:
            entry.done_weeks.append(target)
    else:
        entry.done = True
    entry.save()
    return entry


def uncheck(key: str, week=None) -> CalendarEntry:
    entry = get(key)
    if entry.day:
        target = week or current_week()
        if target in entry.done_weeks:
            entry.done_weeks.remove(target)
    else:
        entry.done = False
    entry.save()
    return entry


def remove(key: str) -> None:
    get(key).delete()


def listing() -> list[CalendarEntry]:
    return sorted(CalendarEntry.objects.all(), key=lambda e: (e.date or 'recurring', e.day, e.order))
