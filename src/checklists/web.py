from flask import Blueprint

from checklists.view import render


def make_checklists_bp(services) -> Blueprint:
    bp = Blueprint('checklists', __name__)

    @bp.get('/checklists')
    @bp.get('/checklists/<key>')
    def page(key: str = ''):
        return render(services)

    return bp
