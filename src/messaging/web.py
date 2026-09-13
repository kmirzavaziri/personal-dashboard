from flask import Blueprint, request

import messaging.service as messaging


def make_messaging_bp(services) -> Blueprint:
    bp = Blueprint('messaging', __name__)

    @bp.post('/api/sms/ingest')
    def sms_ingest():
        payload = request.get_json(silent=True)
        if payload is None:
            payload = {'text': request.get_data(as_text=True)}
        messaging.ingest(services.config, 'sms', payload)
        if services.git is not None:
            services.git.mark_dirty()
        return {'ok': True}

    return bp
