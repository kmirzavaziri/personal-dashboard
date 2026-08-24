from flask import Blueprint

from expenses.view import render


def make_expenses_bp(services) -> Blueprint:
    bp = Blueprint('expenses', __name__)

    @bp.get('/expenses')
    def page():
        return render(services)

    return bp
