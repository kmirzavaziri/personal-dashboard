from flask import jsonify, request

from core.item.item import Item
from core.item.status import status_values
from pkg.model.base import DoesNotExist


def apply_status(kind: str, label: str, key: str):
    valid = status_values(kind)
    status = (request.get_json(silent=True) or {}).get('status', '')
    if status not in valid:
        return f'Invalid status. Use one of: {valid}', 400
    try:
        item = Item.objects.get(key=key, kind=kind)
    except DoesNotExist:
        return f"{label} '{key}' not found", 404
    item.status = status
    item.save()
    return jsonify({'key': key, 'status': status})


def delete_item(kind: str, label: str, key: str):
    try:
        item = Item.objects.get(key=key, kind=kind)
    except DoesNotExist:
        return f"{label} '{key}' not found", 404
    item.delete()
    return jsonify({'key': key, 'deleted': True})
