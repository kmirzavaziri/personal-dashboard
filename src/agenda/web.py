from flask import Blueprint, jsonify, request

from agenda.view import render
import agenda.service as agenda


def make_calendar_bp(services) -> Blueprint:
    bp = Blueprint('calendar', __name__)

    @bp.get('/calendar')
    def page():
        return render(services, request.args.get('offset', 0, type=int))

    @bp.post('/api/calendar/toggle')
    def toggle():
        data = request.get_json(force=True)
        try:
            done = agenda.toggle(data.get('key'), data.get('week') or None)
        except ValueError:
            return jsonify(ok=False), 404
        return jsonify(ok=True, done=done)

    return bp
