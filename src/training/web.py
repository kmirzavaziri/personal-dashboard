from flask import Blueprint, jsonify, request

import training.service as training
from training.view import render


def make_training_bp(services) -> Blueprint:
    bp = Blueprint('training', __name__)

    @bp.get('/training')
    def page():
        return render(services)

    @bp.post('/api/training/set')
    def record_set():
        data = request.get_json(force=True)
        try:
            training.record_set(services.config, str(data['workout']), str(data['exercise']),
                                int(data['number']), float(data['kg']), int(data['reps']))
        except (KeyError, TypeError, ValueError):
            return jsonify(ok=False), 400
        return jsonify(ok=True)

    return bp
