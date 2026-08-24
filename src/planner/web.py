from flask import Blueprint, jsonify, request

from planner.model import PlannerMeta, Task
from planner.view import render


def make_planner_bp(services) -> Blueprint:
    bp = Blueprint('planner', __name__)

    @bp.get('/planner')
    def page():
        return render(services)

    @bp.post('/api/planner/reorder-groups')
    def reorder_groups():
        order = request.get_json(force=True).get('order', [])
        meta = PlannerMeta.objects.get_or_none(key='board') or PlannerMeta(key='board')
        meta.label_order = [str(label) for label in order]
        meta.save()
        return jsonify(ok=True)

    @bp.post('/api/planner/reorder-cards')
    def reorder_cards():
        keys = request.get_json(force=True).get('keys', [])
        for index, key in enumerate(keys):
            task = Task.objects.get_or_none(key=key)
            if task is not None:
                task.order = (index + 1) * 10
                task.save()
        return jsonify(ok=True)

    return bp
