from flask import Blueprint, jsonify, request

import transactions.service as tx_service
from expenses.view import render


def make_expenses_bp(services) -> Blueprint:
    bp = Blueprint('expenses', __name__)

    @bp.get('/expenses')
    def page():
        return render(services)

    @bp.post('/api/transaction/<tx_id>/category')
    def set_transaction_category(tx_id):
        category = (request.get_json(silent=True) or {}).get('category', '')
        if not tx_service.set_category(services.config, tx_id, category):
            return 'not found', 404
        if services.git is not None:
            services.git.mark_dirty()
        return jsonify({'id': tx_id, 'category': category})

    return bp
