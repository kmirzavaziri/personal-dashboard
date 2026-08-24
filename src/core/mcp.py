import json

import yaml
from flask import Blueprint, jsonify, request

from planner.model import Task
from agenda.model import CalendarEntry
import planner.service as planner
import agenda.service as calendar
import core.item.service as items
import styling.service as styling
import health.service as health

PROTOCOL_VERSION = '2024-11-05'


def _task_line(task: Task) -> str:
    labels = ' '.join(f'#{label}' for label in task.labels)
    return f'[{task.status}] {task.key}: {task.title}  {labels}'.rstrip()


def _entry_line(entry: CalendarEntry) -> str:
    when = ('every ' + entry.day) if entry.day else entry.date
    link = f' -> {entry.task_key}' if entry.task_key else ''
    return f'[{when}] {entry.key}: {entry.title or entry.key}{link}'


def planner_add(services, title, labels=None, status='backlog', notes=''):
    return _task_line(planner.add(title, labels, status, notes))


def planner_move(services, key, status):
    return _task_line(planner.move(key, status))


def planner_edit(services, key, title=None, labels=None, status=None, notes=None):
    return _task_line(planner.edit(key, title, labels, status, notes))


def planner_check(services, key):
    return _task_line(planner.check(key))


def planner_rm(services, key):
    planner.remove(key)
    return f'Removed {key}'


def planner_list(services, label=None, status=None):
    return '\n'.join(_task_line(t) for t in planner.listing(label, status)) or '(no tasks)'


def calendar_add(services, title=None, day=None, date_=None, task=None, labels=None, notes=''):
    return _entry_line(calendar.add(title, day, date_, task, labels, notes))


def calendar_edit(services, key, title=None, day=None, date_=None, task=None, labels=None, notes=None, order=None):
    return _entry_line(calendar.edit(key, title, day, date_, task, labels, notes, order))


def calendar_check(services, key, week=None):
    return _entry_line(calendar.check(key, week))


def calendar_uncheck(services, key, week=None):
    return _entry_line(calendar.uncheck(key, week))


def calendar_rm(services, key):
    calendar.remove(key)
    return f'Removed {key}'


def calendar_list(services):
    return '\n'.join(_entry_line(e) for e in calendar.listing()) or '(no entries)'


def report(services):
    return json.dumps(health.report_dict(services.config), ensure_ascii=False)


def item_list(services, kind=None, category=None):
    return json.dumps(items.listing(kind, category), ensure_ascii=False)


def item_create(services, key, data):
    return items.create(key, data)


def item_get(services, key, field):
    value = items.get_field(key, field)
    return yaml.dump(value, allow_unicode=True, sort_keys=False).strip() if value is not None else '(empty)'


def item_set(services, key, field, value, replace=False):
    return items.set_field(services.config, key, field, value, replace)


def item_delete(services, key):
    return items.delete(key)


def item_add_source(services, key, store, id, price=None, url=None, title='', out_of_stock=False,
                    size_ml=None, specs_servings=None, servings_per_item=None, iherb_serving_units=1):
    return items.add_source(services.config, key, store, id, price, url, title, out_of_stock,
                            size_ml, specs_servings, servings_per_item, iherb_serving_units)


def item_set_image(services, key, image_url):
    return items.set_image(services.config, key, image_url)


def item_chosen_source(services, key, store=None):
    return json.dumps(items.chosen_source(key, store))


def sync_images(services):
    return items.sync_images(services.config)


def styling_add(services, store, url, category, goal='', sku=None, title='', price=None,
                image_url='', brand='', sizes=None, no_size_check=False):
    return styling.add(services.config, store, url, category, goal, sku, title, price,
                       image_url, brand, sizes, no_size_check)


def styling_recheck_targets(services):
    return json.dumps(styling.recheck_targets())


def styling_recheck(services, key, sizes):
    return styling.recheck(services.config, key, sizes)


def styling_flag(services, key, labels=None):
    return styling.flag(key, labels)


def styling_move(services, key, status):
    return styling.move(key, status)


_STR = {'type': 'string'}
_INT = {'type': 'integer'}
_BOOL = {'type': 'boolean'}
_NUM = {'type': 'number'}
_LABELS = {'type': 'array', 'items': {'type': 'string'}}
_ANY = {}

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
      'notes': _STR, 'order': _INT}, ['key'], calendar_edit),
    ('calendar_check', 'Mark an entry done (recurring: for the given/current ISO week).',
     {'key': _STR, 'week': _STR}, ['key'], calendar_check),
    ('calendar_uncheck', 'Mark an entry not done.', {'key': _STR, 'week': _STR}, ['key'], calendar_uncheck),
    ('calendar_rm', 'Remove a calendar entry.', {'key': _STR}, ['key'], calendar_rm),
    ('calendar_list', 'List all calendar entries.', {}, [], calendar_list),
    ('report', 'Return the full health plan (meals, nutrient targets, item pool) as JSON.', {}, [], report),
    ('item_list', 'List items as [{key,short_name,kind,status,category}], optionally by kind/category.',
     {'kind': _STR, 'category': _STR}, [], item_list),
    ('item_create', 'Create a new item file from a full data object (key, kind, fields).',
     {'key': _STR, 'data': _ANY}, ['key', 'data'], item_create),
    ('item_get', 'Read one field from an item file (YAML).', {'key': _STR, 'field': _STR}, ['key', 'field'], item_get),
    ('item_set', 'Set or append a field on an item. field may be dotted for nested paths '
     '(e.g. metadata.edible.nutrition). value is any JSON; dicts merge and lists append unless replace=true. '
     'Special: field "image" with a URL downloads it; field "sources" validates + dedups.',
     {'key': _STR, 'field': _STR, 'value': _ANY, 'replace': _BOOL}, ['key', 'field', 'value'], item_set),
    ('item_delete', 'Delete an item file.', {'key': _STR}, ['key'], item_delete),
    ('item_add_source', 'Persist a scraped store source onto an item; the server derives servings and dedups.',
     {'key': _STR, 'store': _STR, 'id': _STR, 'price': _NUM, 'url': _STR, 'title': _STR,
      'out_of_stock': _BOOL, 'size_ml': _NUM, 'specs_servings': _ANY, 'servings_per_item': _ANY,
      'iherb_serving_units': _INT}, ['key', 'store', 'id'], item_add_source),
    ('item_set_image', 'Download an image URL to the item and set its image field.',
     {'key': _STR, 'image_url': _STR}, ['key', 'image_url'], item_set_image),
    ('item_chosen_source', 'Return {store,id,url} of an item source (chosen by default, or a named store).',
     {'key': _STR, 'store': _STR}, ['key'], item_chosen_source),
    ('sync_images', 'Download all remote edible-item image URLs to local storage.', {}, [], sync_images),
    ('styling_add', 'Add a scraped product as a candidate styling item; the server runs the size check.',
     {'store': _STR, 'url': _STR, 'category': _STR, 'goal': _STR, 'sku': _STR, 'title': _STR,
      'price': _NUM, 'image_url': _STR, 'brand': _STR, 'sizes': _LABELS, 'no_size_check': _BOOL},
     ['store', 'url', 'category'], styling_add),
    ('styling_recheck_targets', 'List clothing items with a scrapeable source to recheck: [{key,store,url}].',
     {}, [], styling_recheck_targets),
    ('styling_recheck', 'Recompute size availability for a styling item from freshly scraped sizes.',
     {'key': _STR, 'sizes': _LABELS}, ['key', 'sizes'], styling_recheck),
    ('styling_flag', 'Set concern badges on a styling item; empty clears them.',
     {'key': _STR, 'labels': _LABELS}, ['key'], styling_flag),
    ('styling_move', 'Move a styling item to another status group.',
     {'key': _STR, 'status': _STR}, ['key', 'status'], styling_move),
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
                text = fn(services, **(params.get('arguments') or {}))
                result = {'content': [{'type': 'text', 'text': str(text)}], 'isError': False}
            except Exception as exc:
                result = {'content': [{'type': 'text', 'text': f'Error: {exc}'}], 'isError': True}
        else:
            return jsonify(jsonrpc='2.0', id=mid, error={'code': -32601, 'message': 'method not found'})
        return jsonify(jsonrpc='2.0', id=mid, result=result)

    return bp
