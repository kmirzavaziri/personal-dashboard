from flask import Blueprint

from health.view import render


def make_health_bp(services) -> Blueprint:
    bp = Blueprint('health', __name__)

    @bp.get('/health')
    def page():
        return render(services)

    return bp
