import re
from datetime import date

import typer

from agenda.model import CalendarEntry, DAYS, current_week
from planner.model import Task

calendar_app = typer.Typer(no_args_is_help=True, add_completion=False, help='Manage calendar entries')


def register(root: typer.Typer) -> None:
    root.add_typer(calendar_app, name='calendar')


def _slug(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:60] or 'entry'


def _unique_key(base: str) -> str:
    key, suffix = base, 2
    while CalendarEntry.objects.get_or_none(key=key) is not None:
        key, suffix = f'{base}-{suffix}', suffix + 1
    return key


def _next_order() -> int:
    return max((e.order for e in CalendarEntry.objects.all()), default=0) + 1


def _flatten(labels: list[str]) -> list[str]:
    return [part.strip() for value in labels for part in value.split(',') if part.strip()]


def _get(key: str) -> CalendarEntry:
    entry = CalendarEntry.objects.get_or_none(key=key)
    if entry is None:
        raise SystemExit(f'Entry not found: {key}')
    return entry


def _display_title(entry: CalendarEntry) -> str:
    if entry.title:
        return entry.title
    task = Task.objects.get_or_none(key=entry.task_key)
    return task.title if task else entry.key


def _show(entry: CalendarEntry) -> str:
    when = ('every ' + entry.day) if entry.day else entry.date
    link = f' →{entry.task_key}' if entry.task_key else ''
    labels = ' '.join(f'#{label}' for label in entry.labels)
    return f'  [{when:12}] {entry.key:24} {_display_title(entry)}{link}  {labels}'.rstrip()


@calendar_app.command(help='Add an entry. Use --day for a weekly recurring entry or --date for a one-off.')
def add(
    title: str = typer.Argument(None, help='Entry title (optional if --task is given)'),
    day: str = typer.Option(None, '--day', '-d', help=f"Recurring weekday: {', '.join(DAYS)}"),
    on: str = typer.Option(None, '--date', help='One-off date, YYYY-MM-DD'),
    task: str = typer.Option(None, '--task', help='Link to a planner task key'),
    label: list[str] = typer.Option([], '--label', '-l', help='Label(s), repeatable or comma-separated'),
    notes: str = typer.Option('', '--notes', '-n', help='Optional notes'),
):
    if bool(day) == bool(on):
        raise SystemExit('Pass exactly one of --day (weekly recurring) or --date YYYY-MM-DD (one-off).')
    if day and day not in DAYS:
        raise SystemExit(f"Unknown day '{day}'. Valid: {', '.join(DAYS)}")
    if on:
        try:
            date.fromisoformat(on)
        except ValueError:
            raise SystemExit('Date must be YYYY-MM-DD.')
    if task and Task.objects.get_or_none(key=task) is None:
        raise SystemExit(f'No such task: {task}')
    if not title:
        if not task:
            raise SystemExit('Provide a title, or --task to pull it from a planner task.')
        title = ''
    display = title or Task.objects.get(key=task).title
    entry = CalendarEntry(
        key=_unique_key(_slug(display)),
        title=title,
        task_key=task or '',
        day=day or '',
        date=on or '',
        labels=_flatten(label),
        notes=notes,
        order=_next_order(),
    )
    entry.save()
    print(_show(entry))


@calendar_app.command('ls', help='List entries.')
def ls():
    entries = sorted(CalendarEntry.objects.all(), key=lambda e: (e.date or 'recurring', e.day, e.order))
    for entry in entries:
        print(_show(entry))
    print(f'  ({len(entries)} entr{"ies" if len(entries) != 1 else "y"})')


@calendar_app.command(help='Edit an entry. Only the fields you pass change.')
def edit(
    key: str = typer.Argument(..., help='Entry key'),
    title: str = typer.Option(None, '--title', '-t', help='New title'),
    day: str = typer.Option(None, '--day', '-d', help='Move to a recurring weekday (clears any date)'),
    on: str = typer.Option(None, '--date', help='Move to a one-off date (clears any weekday)'),
    task: str = typer.Option(None, '--task', help="Link task key; pass '' to unlink"),
    label: list[str] = typer.Option(None, '--label', '-l', help='Replacement label(s); empty string clears'),
    notes: str = typer.Option(None, '--notes', '-n', help='New notes'),
    order: int = typer.Option(None, '--order', '-o', help='Sort order within its day/date (lower shows first)'),
):
    entry = _get(key)
    if title is not None:
        entry.title = title
    if order is not None:
        entry.order = order
    if day is not None:
        if day not in DAYS:
            raise SystemExit(f"Unknown day '{day}'. Valid: {', '.join(DAYS)}")
        entry.day, entry.date = day, ''
    if on is not None:
        try:
            date.fromisoformat(on)
        except ValueError:
            raise SystemExit('Date must be YYYY-MM-DD.')
        entry.date, entry.day = on, ''
    if task is not None:
        if task and Task.objects.get_or_none(key=task) is None:
            raise SystemExit(f'No such task: {task}')
        entry.task_key = task
    if label is not None:
        entry.labels = _flatten(label)
    if notes is not None:
        entry.notes = notes
    entry.save()
    print(_show(entry))


@calendar_app.command(help='Mark an entry done (recurring: for a week, defaults to the current week).')
def check(
    key: str = typer.Argument(..., help='Entry key'),
    week: str = typer.Option(None, '--week', '-w', help='ISO week for recurring entries, e.g. 2026-W34'),
):
    entry = _get(key)
    if entry.day:
        target = week or current_week()
        if target not in entry.done_weeks:
            entry.done_weeks.append(target)
    else:
        entry.done = True
    entry.save()
    print(_show(entry))


@calendar_app.command(help='Mark an entry not done.')
def uncheck(
    key: str = typer.Argument(..., help='Entry key'),
    week: str = typer.Option(None, '--week', '-w', help='ISO week for recurring entries, e.g. 2026-W34'),
):
    entry = _get(key)
    if entry.day:
        target = week or current_week()
        if target in entry.done_weeks:
            entry.done_weeks.remove(target)
    else:
        entry.done = False
    entry.save()
    print(_show(entry))


@calendar_app.command(help='Remove an entry.')
def rm(key: str = typer.Argument(..., help='Entry key')):
    entry = _get(key)
    entry.delete()
    print(f'  Removed {key}')
