from pathlib import Path
from collections import defaultdict
from datetime import date

from core.labels import UNLABELED, label_colors
from core.web.templating import make_env
from agenda.model import CalendarEntry, DAYS, DAY_LABELS, MONTHS, week_offset
from planner.model import PlannerMeta, Task

HERE = Path(__file__).parent

_jinja = make_env(HERE)


def _grouped(tasks: list[Task], label_order: list[str]) -> list[tuple[str, list[Task]]]:
    groups: dict[str, list[Task]] = defaultdict(list)
    for task in tasks:
        groups[task.labels[0] if task.labels else UNLABELED].append(task)

    def rank(name: str):
        if name in label_order:
            return (0, label_order.index(name))
        return (1, min(t.order for t in groups[name]))

    return [(name, sorted(groups[name], key=lambda t: t.order)) for name in sorted(groups, key=rank)]


def _links_by_task() -> dict[str, list[CalendarEntry]]:
    out: dict[str, list[CalendarEntry]] = defaultdict(list)
    for entry in CalendarEntry.objects.all():
        if entry.task_key:
            out[entry.task_key].append(entry)
    return out


def _schedule_chip(entry: CalendarEntry) -> dict:
    if entry.day:
        return {'text': DAY_LABELS[DAYS.index(entry.day)] + 's', 'offset': 0}
    day = date.fromisoformat(entry.date)
    return {'text': f'{DAY_LABELS[day.weekday()]} · {MONTHS[day.month - 1]} {day.day}', 'offset': week_offset(day)}


def _placement(task: Task, links: list[CalendarEntry], today: date) -> tuple[str, object]:
    if task.status == 'done':
        return 'done', task.order
    if not links:
        return task.status, task.order
    recurring = any(e.day for e in links)
    dated = [e for e in links if e.date]
    future = sorted(date.fromisoformat(e.date) for e in dated if date.fromisoformat(e.date) >= today)
    past = sorted((date.fromisoformat(e.date) for e in dated if date.fromisoformat(e.date) < today), reverse=True)
    if recurring or future:
        return 'planned', future[0] if future else date.max
    if past:
        return 'missed', past[0]
    return task.status, task.order


def render(services) -> str:
    tasks = Task.objects.all()
    links = _links_by_task()
    today = date.today()
    meta = PlannerMeta.objects.get_or_none(key='board')
    label_order = meta.label_order if meta else []

    columns: dict[str, list[tuple[object, Task]]] = defaultdict(list)
    for task in tasks:
        column, sort_key = _placement(task, links.get(task.key, []), today)
        columns[column].append((sort_key, task))

    def ordered(column: str, reverse: bool = False) -> list[Task]:
        return [task for _, task in sorted(columns[column], key=lambda pair: pair[0], reverse=reverse)]

    schedules = {key: [_schedule_chip(e) for e in entries] for key, entries in links.items()}

    template = _jinja.get_template('board.html')
    return template.render(
        backlog_groups=_grouped(ordered('backlog'), label_order),
        picks=ordered('next'),
        planned=ordered('planned'),
        missed=ordered('missed', reverse=True),
        done=ordered('done'),
        counts={
            'backlog': len(columns['backlog']),
            'next': len(columns['next']),
            'planned': len(columns['planned']),
            'missed': len(columns['missed']),
            'done': len(columns['done']),
        },
        label_colors=label_colors(tasks),
        schedules=schedules,
    )
