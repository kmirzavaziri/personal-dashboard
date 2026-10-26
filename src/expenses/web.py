from flask import Blueprint, jsonify, redirect, request
from pydantic import ValidationError

import transactions.service as tx_service
from expenses.budget import sub_categories
from transactions.ledger import Ledger
from expenses.view import render, render_card_periods, render_previous_periods, render_rows, render_search, render_vendor_rows
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
    @bp.get('/expenses/<any(budget, transactions, categorize, trends):tab>')
    def page(tab=None):
        return render(services)

    @bp.get('/expenses/<any(spending, budgets):tab>')
    def renamed_tab(tab):
        return redirect('/expenses/budget')

    @bp.get('/expenses/categorize/rows')
    def vendor_rows():
        return render_vendor_rows(services)

    @bp.get('/expenses/periods')
    def previous_periods():
        return render_previous_periods(services, request.args['before'], int(request.args.get('count', 3)))

    @bp.get('/expenses/rows')
    def rows():
        ids = [tx_id for tx_id in request.args.get('ids', '').split(',') if tx_id]
        return render_rows(services, ids, request.args.get('account') == '1')

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
        category, line = body().get('category', ''), body().get('line', '')
        if line:
            sub_category = sub_categories(services.config).get(line)
            if sub_category is None or sub_category.category != category:
                raise ValueError(f'{line!r} is not a sub-category of {category!r}')
            found = tx_service.set_budget_line(services.config, tx_id, category, line)
        else:
            found = tx_service.set_category(services.config, tx_id, category)
        if not found:
            return 'transaction not found', 404
        return changed({'id': tx_id, 'category': category, 'line': line})

    @bp.post('/api/transaction/<tx_id>/description')
    def set_transaction_description(tx_id):
        description = body().get('description', '')
        if not tx_service.set_description(services.config, tx_id, description):
            return 'transaction not found', 404
        return changed({'id': tx_id, 'description': description})

    @bp.post('/api/transaction/<tx_id>/voided')
    def set_transaction_voided(tx_id):
        voided = bool(body().get('voided', True))
        if not tx_service.set_voided(services.config, tx_id, voided):
            return 'transaction not found', 404
        return changed({'id': tx_id, 'voided': voided})

    @bp.post('/api/transaction/<tx_id>/settled')
    def set_transaction_settled(tx_id):
        settled = bool(body().get('settled', True))
        if not tx_service.set_settled(services.config, tx_id, settled):
            return 'transaction not found', 404
        return changed({'id': tx_id, 'settled': settled})

    @bp.post('/api/transaction/<tx_id>/note')
    def set_transaction_note(tx_id):
        note = body().get('note', '').strip()
        if not tx_service.set_note(services.config, tx_id, note):
            return 'transaction not found', 404
        return changed({'id': tx_id, 'note': note})

    @bp.post('/api/transaction/<tx_id>/splits')
    def set_transaction_splits(tx_id):
        splits = body().get('splits', [])
        unknown = [split.get('line') for split in splits if split.get('line') not in sub_categories(services.config)]
        if unknown:
            raise ValueError(f'unknown sub-categories: {unknown}')
        if not tx_service.set_splits(services.config, tx_id, splits):
            return 'transaction not found', 404
        return changed({'id': tx_id, 'splits': splits})

    @bp.post('/api/periods/<period_key>/last')
    def end_period_at(period_key):
        following = tx_service.end_period_at(services.config, Ledger.load(services.config), period_key, body().get('tx_id', ''))
        return changed({'period': period_key, 'following': following})

    @bp.post('/api/vendors/assign')
    def assign_vendor():
        payload = body()
        vendor = (payload.get('vendor') or '').strip()
        if not vendor:
            return 'vendor is required', 400
        tx_service.assign_vendor(services.config, vendor, payload.get('assignments') or [])
        return changed({'vendor': vendor})

    @bp.post('/api/categories')
    def create_category():
        category = tx_service.create_category(body().get('name', ''))
        return changed({'key': category.key, 'name': category.name})

    @bp.put('/api/categories/<key>')
    def rename_category(key):
        category = tx_service.rename_category(key, body().get('name', ''))
        return changed({'key': category.key, 'name': category.name})

    @bp.delete('/api/categories/<key>')
    def delete_category(key):
        released = tx_service.delete_category(services.config, key, body().get('move_rules_to', ''))
        return changed({'deleted': key, 'released': released})

    return bp
