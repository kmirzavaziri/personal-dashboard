from flask import Blueprint, jsonify, request

from planner.model import Task
from agenda.model import CalendarEntry
import planner.service as planner
import agenda.service as calendar

PROTOCOL_VERSION = '2024-11-05'


def _task_line(task: Task) -> str:
    labels = ' '.join(f'#{label}' for label in task.labels)
    return f'[{task.status}] {task.key}: {task.title}  {labels}'.rstrip()


def _entry_line(entry: CalendarEntry) -> str:
    when = ('every ' + entry.day) if entry.day else entry.date
    link = f' -> {entry.task_key}' if entry.task_key else ''
    return f'[{when}] {entry.key}: {entry.title or entry.key}{link}'


def planner_add(title, labels=None, status='backlog', notes=''):
    return _task_line(planner.add(title, labels, status, notes))


def planner_move(key, status):
    return _task_line(planner.move(key, status))


def planner_edit(key, title=None, labels=None, status=None, notes=None):
    return _task_line(planner.edit(key, title, labels, status, notes))


def planner_check(key):
    return _task_line(planner.check(key))


def planner_rm(key):
    planner.remove(key)
    return f'Removed {key}'


def planner_list(label=None, status=None):
    return '\n'.join(_task_line(t) for t in planner.listing(label, status)) or '(no tasks)'


def calendar_add(title=None, day=None, date_=None, task=None, labels=None, notes=''):
    return _entry_line(calendar.add(title, day, date_, task, labels, notes))


def calendar_edit(key, title=None, day=None, date_=None, task=None, labels=None, notes=None, order=None):
    return _entry_line(calendar.edit(key, title, day, date_, task, labels, notes, order))


def calendar_check(key, week=None):
    return _entry_line(calendar.check(key, week))


def calendar_uncheck(key, week=None):
    return _entry_line(calendar.uncheck(key, week))


def calendar_rm(key):
    calendar.remove(key)
    return f'Removed {key}'


def calendar_list():
    return '\n'.join(_entry_line(e) for e in calendar.listing()) or '(no entries)'


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
