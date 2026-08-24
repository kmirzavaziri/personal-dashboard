import re

from flask import Blueprint, abort, jsonify, request

from mac.view import render, render_term
from mac.controller import (
    status as mac_status,
    extend as mac_extend,
    sleep_now as mac_sleep_now,
)
from mac.sessions import send_key as mac_send_key, start_command as mac_start_command

_SOCK_RE = re.compile(r'[A-Za-z0-9_.-]+')


def make_mac_bp(services) -> Blueprint:
    bp = Blueprint('mac', __name__)

    @bp.get('/mac')
    def page():
        return render(services)

    @bp.get('/mac/term')
    def term():
        sock = request.args.get('sock', '')
        if sock and not _SOCK_RE.fullmatch(sock):
            abort(400)
        return render_term(sock)

    @bp.get('/api/mac/status')
    def status_route():
        return jsonify(mac_status())

    @bp.post('/api/mac/extend')
    def extend_route():
        mac_extend(int(request.args.get('min', 30)))
        return jsonify(mac_status())

    @bp.post('/api/mac/off')
    def off_route():
        mac_sleep_now()
        return jsonify(mac_status())

    @bp.post('/api/mac/run')
    def run_route():
        try:
            sock = mac_start_command(request.args.get('command', ''), request.args.get('cwd', ''))
        except ValueError as e:
            return jsonify({'error': str(e)}), 400
        return jsonify({'sock': sock})

    @bp.post('/api/mac/keys')
    def keys_route():
        sock = request.args.get('sock', '')
        if not _SOCK_RE.fullmatch(sock):
            abort(400)
        return jsonify({'sent': mac_send_key(sock, request.args.get('key', ''))})

    return bp
