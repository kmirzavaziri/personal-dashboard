from datetime import date

from flask import Blueprint, jsonify, request

from planner.model import STATUSES, Task
from planner.cli import _slug, _unique_key, _next_order, _flatten
from agenda.model import CalendarEntry, DAYS, current_week
from agenda.cli import (
    _slug as _cslug, _unique_key as _cunique, _next_order as _cnext, _flatten as _cflatten,
)

PROTOCOL_VERSION = '2024-11-05'


def _labels(value) -> list[str]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _task_line(task: Task) -> str:
    labels = ' '.join(f'#{label}' for label in task.labels)
    return f'[{task.status}] {task.key}: {task.title}  {labels}'.rstrip()


def _entry_line(entry: CalendarEntry) -> str:
    when = ('every ' + entry.day) if entry.day else entry.date
    link = f' -> {entry.task_key}' if entry.task_key else ''
    return f'[{when}] {entry.key}: {entry.title or entry.key}{link}'


def _get_task(key: str) -> Task:
    task = Task.objects.get_or_none(key=key)
    if task is None:
        raise ValueError(f'Task not found: {key}')
    return task


def _get_entry(key: str) -> CalendarEntry:
    entry = CalendarEntry.objects.get_or_none(key=key)
    if entry is None:
        raise ValueError(f'Entry not found: {key}')
    return entry


def planner_add(title, labels=None, status='backlog', notes=''):
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    task = Task(key=_unique_key(_slug(title)), title=title, labels=_flatten(_labels(labels)),
                status=status, order=_next_order(), notes=notes)
    task.save()
    return _task_line(task)


def planner_move(key, status):
    if status not in STATUSES:
        raise ValueError(f"status must be one of {', '.join(STATUSES)}")
    task = _get_task(key)
    task.status = status
    task.save()
    return _task_line(task)


def planner_edit(key, title=None, labels=None, status=None, notes=None):
    task = _get_task(key)
    if title is not None:
        task.title = title
    if labels is not None:
        task.labels = _flatten(_labels(labels))
    if status is not None:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        task.status = status
    if notes is not None:
        task.notes = notes
    task.save()
    return _task_line(task)


def planner_check(key):
    return planner_move(key, 'done')


def planner_rm(key):
    _get_task(key).delete()
    return f'Removed {key}'


def planner_list(label=None, status=None):
    tasks = sorted(Task.objects.all(), key=lambda t: (t.status, t.order))
    if label:
        tasks = [t for t in tasks if label in t.labels]
    if status:
        tasks = [t for t in tasks if t.status == status]
    return '\n'.join(_task_line(t) for t in tasks) or '(no tasks)'


def calendar_add(title=None, day=None, date_=None, task=None, labels=None, notes=''):
    if bool(day) == bool(date_):
        raise ValueError('pass exactly one of day (weekday) or date (YYYY-MM-DD)')
    if day and day not in DAYS:
        raise ValueError(f"day must be one of {', '.join(DAYS)}")
    if date_:
        date.fromisoformat(date_)
    if task and Task.objects.get_or_none(key=task) is None:
        raise ValueError(f'No such task: {task}')
    if not title and not task:
        raise ValueError('provide a title, or task to pull it from')
    display = title or Task.objects.get(key=task).title
    entry = CalendarEntry(key=_cunique(_cslug(display)), title=title or '', task_key=task or '',
                          day=day or '', date=date_ or '', labels=_cflatten(_labels(labels)),
                          notes=notes, order=_cnext())
    entry.save()
    return _entry_line(entry)


def calendar_edit(key, title=None, day=None, date_=None, task=None, labels=None, notes=None, order=None):
    entry = _get_entry(key)
    if title is not None:
        entry.title = title
    if day is not None:
        if day not in DAYS:
            raise ValueError(f"day must be one of {', '.join(DAYS)}")
        entry.day, entry.date = day, ''
    if date_ is not None:
        date.fromisoformat(date_)
        entry.date, entry.day = date_, ''
    if task is not None:
        entry.task_key = task
    if labels is not None:
        entry.labels = _cflatten(_labels(labels))
    if notes is not None:
        entry.notes = notes
    if order is not None:
        entry.order = int(order)
    entry.save()
    return _entry_line(entry)


def calendar_check(key, week=None):
    entry = _get_entry(key)
    if entry.day:
        target = week or current_week()
        if target not in entry.done_weeks:
            entry.done_weeks.append(target)
    else:
        entry.done = True
    entry.save()
    return _entry_line(entry)


def calendar_uncheck(key, week=None):
    entry = _get_entry(key)
    if entry.day:
        target = week or current_week()
        if target in entry.done_weeks:
            entry.done_weeks.remove(target)
    else:
        entry.done = False
    entry.save()
    return _entry_line(entry)


def calendar_rm(key):
    _get_entry(key).delete()
    return f'Removed {key}'


def calendar_list():
    entries = sorted(CalendarEntry.objects.all(), key=lambda e: (e.date or 'recurring', e.day, e.order))
    return '\n'.join(_entry_line(e) for e in entries) or '(no entries)'


_STR = {'type': 'string'}
_LABELS = {'type': 'array', 'items': {'type': 'string'}}

TOOLS = [
    ('planner_add', 'Add a task to the board.',
     {'title': _STR, 'labels': _LABELS, 'status': _STR, 'notes': _STR}, ['title'], planner_add),
    ('planner_move', 'Move a task to a status (backlog/next/done).',
     {'key': _STR, 'status': _STR}, ['key', 'status'], planner_move),
    ('planner_edit', 'Edit a task; only passed fields change.',
     {'key': _STR, 'title': _STR, 'labels': _LABELS, 'status': _STR, 'notes': _STR}, ['key'], planner_edit),
    ('planner_check', 'Mark a task done.', {'key': _STR}, ['key'], planner_check),
    ('planner_rm', 'Remove a task.', {'key': _STR}, ['key'], planner_rm),
    ('planner_list', 'List tasks, optionally filtered.',
     {'label': _STR, 'status': _STR}, [], planner_list),
    ('calendar_add', 'Add a calendar entry: day (recurring weekday) OR date_ (YYYY-MM-DD); optional task link.',
     {'title': _STR, 'day': _STR, 'date_': _STR, 'task': _STR, 'labels': _LABELS, 'notes': _STR}, [], calendar_add),
    ('calendar_edit', 'Edit a calendar entry; only passed fields change.',
     {'key': _STR, 'title': _STR, 'day': _STR, 'date_': _STR, 'task': _STR, 'labels': _LABELS,
      'notes': _STR, 'order': {'type': 'integer'}}, ['key'], calendar_edit),
    ('calendar_check', 'Mark an entry done (recurring: for the given/current ISO week).',
     {'key': _STR, 'week': _STR}, ['key'], calendar_check),
    ('calendar_uncheck', 'Mark an entry not done.', {'key': _STR, 'week': _STR}, ['key'], calendar_uncheck),
    ('calendar_rm', 'Remove a calendar entry.', {'key': _STR}, ['key'], calendar_rm),
    ('calendar_list', 'List all calendar entries.', {}, [], calendar_list),
]

_DISPATCH = {name: fn for name, _d, _p, _r, fn in TOOLS}


def _tool_defs() -> list[dict]:
    return [
        {'name': name, 'description': desc,
         'inputSchema': {'type': 'object', 'properties': props, 'required': required}}
        for name, desc, props, required, _fn in TOOLS
    ]


def make_mcp_bp(services) -> Blueprint:
    bp = Blueprint('mcp', __name__)
    token = services.config.mcp_token

    def _authorized() -> bool:
        if not token:
            return True
        return request.headers.get('Authorization') == f'Bearer {token}'

    @bp.post('/mcp')
    def endpoint():
        if not _authorized():
            return jsonify(error='unauthorized'), 401
        msg = request.get_json(force=True, silent=True) or {}
        method, mid, params = msg.get('method'), msg.get('id'), msg.get('params') or {}
        if mid is None:
            return '', 202
        if method == 'initialize':
            result = {'protocolVersion': PROTOCOL_VERSION, 'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'personal-dashboard', 'version': '1'}}
        elif method == 'tools/list':
            result = {'tools': _tool_defs()}
        elif method == 'tools/call':
            fn = _DISPATCH.get(params.get('name'))
            if fn is None:
                return jsonify(jsonrpc='2.0', id=mid, error={'code': -32601, 'message': 'unknown tool'})
            try:
                text = fn(**(params.get('arguments') or {}))
                result = {'content': [{'type': 'text', 'text': str(text)}], 'isError': False}
            except Exception as exc:
                result = {'content': [{'type': 'text', 'text': f'Error: {exc}'}], 'isError': True}
        else:
            return jsonify(jsonrpc='2.0', id=mid, error={'code': -32601, 'message': 'method not found'})
        return jsonify(jsonrpc='2.0', id=mid, result=result)

    return bp
