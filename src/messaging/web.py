from flask import Blueprint, request

import transactions.service as transactions


def make_messaging_bp(services) -> Blueprint:
    bp = Blueprint('messaging', __name__)

    @bp.post('/api/ingest/<source>')
    def ingest(source):
        body = request.get_json(silent=True)
        if body is None:
            body = {'text': request.get_data(as_text=True)}
        outcome = transactions.receive(services.config, source, body if isinstance(body, list) else [body])
        if services.git is not None:
            services.git.mark_dirty()
        return {'ok': True, 'outcome': dict(outcome)}

    @bp.post('/api/ingest/wallet/transaction')
    def wallet_transaction():
        body = request.get_json(silent=True)
        if body is None:
            body = {'body': request.get_data(as_text=True)}
        outcome = transactions.receive_wallet(services.config, body)
        if services.git is not None:
            services.git.mark_dirty()
        return {'ok': True, 'outcome': dict(outcome)}

    return bp
