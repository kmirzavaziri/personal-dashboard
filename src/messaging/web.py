from flask import Blueprint, request

import messaging.service as messaging
import transactions.service as transactions


def make_messaging_bp(services) -> Blueprint:
    bp = Blueprint('messaging', __name__)

    @bp.post('/api/ingest/<source>')
    def ingest(source):
        payload = request.get_json(silent=True)
        if payload is None:
            payload = {'text': request.get_data(as_text=True)}
        entry = messaging.ingest(services.config, source, payload)
        try:
            transactions.ingest(services.config, entry)
        except Exception:
            pass
        if services.git is not None:
            services.git.mark_dirty()
        return {'ok': True}

    return bp
