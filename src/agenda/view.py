from datetime import date, timedelta
from pathlib import Path

from core.labels import UNLABELED, colors_for
from core.web.templating import make_env
from agenda.model import CalendarEntry, DAYS, DAY_LABELS, MONTHS, monday_of, week_str
from planner.model import Task

HERE = Path(__file__).parent

_jinja = make_env(HERE)


def _eff_labels(entry: CalendarEntry, tasks: dict[str, Task]) -> list[str]:
    if entry.labels:
        return entry.labels
    task = tasks.get(entry.task_key)
    return task.labels if task else []


def _title(entry: CalendarEntry, tasks: dict[str, Task]) -> str:
    if entry.title:
        return entry.title
    task = tasks.get(entry.task_key)
    return task.title if task else entry.key


def _when(entry: CalendarEntry) -> str:
    if entry.day:
        return 'Every ' + DAY_LABELS[DAYS.index(entry.day)]
    day = date.fromisoformat(entry.date)
    return f'{MONTHS[day.month - 1]} {day.day}'


def _card(entry: CalendarEntry, week: str, tasks: dict[str, Task], colors: dict[str, str]) -> dict:
    labels = _eff_labels(entry, tasks)
    return {
        'key': entry.key,
        'title': _title(entry, tasks),
        'labels': labels,
        'notes': entry.notes,
        'color': colors[labels[0]] if labels else colors[UNLABELED],
        'done': (week in entry.done_weeks) if entry.day else entry.done,
        'when': _when(entry),
        'recurring': bool(entry.day),
        'task_key': entry.task_key,
    }


def render(services, offset: int = 0) -> str:
    entries = CalendarEntry.objects.all()
    tasks = {task.key: task for task in Task.objects.all()}
    colors = colors_for({label for entry in entries for label in _eff_labels(entry, tasks)})

    today = date.today()
    monday = monday_of(today) + timedelta(weeks=offset)
    week = week_str(monday)

    days = []
    for index, name in enumerate(DAYS):
        day = monday + timedelta(days=index)
        iso = day.isoformat()
        items = sorted((e for e in entries if e.day == name or e.date == iso), key=lambda e: e.order)
        days.append({
            'label': DAY_LABELS[index],
            'num': day.day,
            'is_today': day == today,
            'cards': [_card(entry, week, tasks, colors) for entry in items],
        })

    sunday = monday + timedelta(days=6)
    span = f'{MONTHS[monday.month - 1]} {monday.day} – {MONTHS[sunday.month - 1]} {sunday.day}, {sunday.year}'

    template = _jinja.get_template('calendar.html')
    return template.render(days=days, week=week, offset=offset, span=span, colors=colors, is_current=offset == 0)
