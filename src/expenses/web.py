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

    @bp.post('/api/transaction/<tx_id>/note')
    def set_transaction_note(tx_id):
        note = (request.get_json(silent=True) or {}).get('note', '').strip()
        if not tx_service.set_note(services.config, tx_id, note):
            return 'not found', 404
        if services.git is not None:
            services.git.mark_dirty()
        return jsonify({'id': tx_id, 'note': note})

    @bp.post('/api/vendor/category')
    def categorize_vendor():
        body = request.get_json(silent=True) or {}
        vendor, category = body.get('vendor', '').strip(), body.get('category', '').strip()
        if not vendor or not category:
            return 'vendor and category are required', 400
        updated = tx_service.categorize_vendor(services.config, vendor, category)
        if services.git is not None:
            services.git.mark_dirty()
        return jsonify({'vendor': vendor, 'category': category, 'updated': updated})

    return bp
