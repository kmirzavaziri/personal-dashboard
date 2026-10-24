from flask import Blueprint, jsonify, request
from pydantic import ValidationError

import transactions.service as tx_service
from expenses.view import render, render_card_periods, render_previous_periods, render_search
from pkg.model.base import DoesNotExist


def make_expenses_bp(services) -> Blueprint:
    bp = Blueprint('expenses', __name__)

    def body() -> dict:
        return request.get_json(silent=True) or {}

    def changed(payload):
        if services.git is not None:
            services.git.mark_dirty()
        return jsonify(payload)

    @bp.errorhandler(ValueError)
    @bp.errorhandler(ValidationError)
    def invalid(error):
        return str(error), 400

    @bp.errorhandler(DoesNotExist)
    def missing(error):
        return str(error), 404

    @bp.get('/expenses')
    def page():
        return render(services)

    @bp.get('/expenses/periods')
    def previous_periods():
        return render_previous_periods(services, request.args['before'], int(request.args.get('count', 3)))

    @bp.get('/expenses/search')
    def search():
        args = request.args
        return render_search(services, args.get('q', ''), args.get('account', ''), int(args.get('limit', 200)))

    @bp.get('/expenses/cards/periods')
    def card_periods():
        args = request.args
        return render_card_periods(services, args['account'], args['before'], int(args.get('count', 2)))

    @bp.post('/api/transaction/<tx_id>/category')
    def set_transaction_category(tx_id):
        category = body().get('category', '')
        if not tx_service.set_category(services.config, tx_id, category):
            return 'transaction not found', 404
        return changed({'id': tx_id, 'category': category})

    @bp.post('/api/transaction/<tx_id>/note')
    def set_transaction_note(tx_id):
        note = body().get('note', '').strip()
        if not tx_service.set_note(services.config, tx_id, note):
            return 'transaction not found', 404
        return changed({'id': tx_id, 'note': note})

    @bp.post('/api/vendor/category')
    def categorize_vendor():
        vendor, category = body().get('vendor', '').strip(), body().get('category', '').strip()
        if not vendor or not category:
            return 'vendor and category are required', 400
        tx_service.categorize_vendor(vendor, category)
        return changed({'vendor': vendor, 'category': category})

    @bp.post('/api/categories')
    def create_category():
        category = tx_service.create_category(body().get('name', ''))
        return changed({'key': category.key, 'name': category.name})

    @bp.put('/api/categories/<key>')
    def save_category(key):
        payload = body()
        category = tx_service.save_category(services.config, key, payload.get('name', ''), payload.get('rules', []))
        return changed({'key': category.key, 'name': category.name})

    @bp.delete('/api/categories/<key>')
    def delete_category(key):
        moved = tx_service.delete_category(services.config, key, body().get('move_to', ''))
        return changed({'deleted': key, 'reassigned': moved})

    return bp
