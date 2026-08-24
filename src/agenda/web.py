from flask import Blueprint, jsonify, request

from agenda.model import CalendarEntry
from agenda.view import render


def make_calendar_bp(services) -> Blueprint:
    bp = Blueprint('calendar', __name__)

    @bp.get('/calendar')
    def page():
        return render(services, request.args.get('offset', 0, type=int))

    @bp.post('/api/calendar/toggle')
    def toggle():
        data = request.get_json(force=True)
        entry = CalendarEntry.objects.get_or_none(key=data.get('key'))
        if entry is None:
            return jsonify(ok=False), 404
        if entry.day:
            week = data.get('week', '')
            if week in entry.done_weeks:
                entry.done_weeks.remove(week)
            else:
                entry.done_weeks.append(week)
            entry.save()
            return jsonify(ok=True, done=week in entry.done_weeks)
        entry.done = not entry.done
        entry.save()
        return jsonify(ok=True, done=entry.done)

    return bp
