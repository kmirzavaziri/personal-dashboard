from flask import Blueprint

from styling.view import render
from core.web.item_api import apply_status, delete_item


def make_styling_bp(services) -> Blueprint:
    bp = Blueprint('styling', __name__)

    @bp.get('/styling')
    def page():
        return render(services)

    @bp.post('/api/styling/<key>/status')
    def styling_status(key: str):
        return apply_status('clothing', 'Styling item', key)

    @bp.post('/api/styling/<key>/delete')
    def styling_delete(key: str):
        return delete_item('clothing', 'Styling item', key)

    return bp
