from flask import Blueprint

from shopping_list.view import render
from core.web.item_api import apply_status


def make_shopping_bp(services) -> Blueprint:
    bp = Blueprint('shopping', __name__)

    @bp.get('/shopping')
    def page():
        return render(services)

    @bp.post('/api/item/<key>/status')
    def item_status(key: str):
        return apply_status('edible', 'Item', key)

    @bp.post('/api/gear/<key>/status')
    def gear_status(key: str):
        return apply_status('durable', 'Gear item', key)

    return bp
