import atexit
import hashlib
import hmac

from flask import Flask, Response, request, send_from_directory

from core.config import Config
from core.gitdata import GitData
from core.mcp import make_mcp_bp
from core.services import Services
from core.web.templating import make_env
from pkg.model.base import Model
from health.web import make_health_bp
from shopping_list.web import make_shopping_bp
from styling.web import make_styling_bp
from expenses.web import make_expenses_bp
from mac.web import make_mac_bp
from planner.web import make_planner_bp
from agenda.web import make_calendar_bp
from mac.net import display_hosts


def _is_local_host(host: str) -> bool:
    return (host in ('localhost', '127.0.0.1', '0.0.0.0', '::1')
            or host.endswith('.local')
            or host.startswith(('192.168.', '10.')))


def _ui_host_allowed(host: str, web_hosts: tuple[str, ...]) -> bool:
    host = host.split(':')[0]
    if web_hosts:
        return host in web_hosts
    return _is_local_host(host)


def _valid_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith('sha256='):
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest('sha256=' + digest, header)


def create_app(services: Services) -> Flask:
    config = services.config
    app = Flask(__name__, static_folder=None)

    blueprints = [make_health_bp, make_shopping_bp, make_styling_bp,
                  make_expenses_bp, make_planner_bp, make_calendar_bp]
    if config.enable_mac:
        blueprints.append(make_mac_bp)
    for make_bp in blueprints:
        app.register_blueprint(make_bp(services))
    app.register_blueprint(make_mcp_bp(services))

    @app.get('/healthz')
    def healthz():
        return 'ok'

    @app.get('/version')
    def version():
        return {'sha': config.git_sha, 'branch': config.git_branch}

    if config.cf_proxy_secret:
        @app.before_request
        def require_cloudflare():
            if request.path == '/healthz':
                return None
            if request.headers.get('X-Proxy-Secret') != config.cf_proxy_secret:
                return 'forbidden', 403

    @app.before_request
    def authorize():
        if request.path == '/healthz':
            return None
        if _ui_host_allowed(request.host, config.web_hosts):
            return None
        if request.path == '/api/webhook':
            return None
        if config.mcp_token and hmac.compare_digest(
                request.headers.get('Authorization', ''), f'Bearer {config.mcp_token}'):
            return None
        return {'ok': False}, 401

    env = make_env(config.templates)

    @app.get('/')
    def home():
        return env.get_template('home.html').render(enable_mac=config.enable_mac)

    @app.get('/manifest.webmanifest')
    def manifest():
        return Response((config.templates / 'manifest.webmanifest').read_bytes(),
                        mimetype='application/manifest+json')

    @app.get('/sw.js')
    def service_worker():
        return Response((config.templates / 'sw.js').read_bytes(),
                        mimetype='application/javascript')

    @app.get('/storage/<path:filename>')
    def storage(filename: str):
        return send_from_directory(config.storage, filename)

    if config.git_backup:
        git = GitData(config.data_dir, config.git_branch, config.git_push_debounce)
        git.pull()
        Model.on_change(git.mark_dirty)
        atexit.register(git.flush)

        @app.post('/api/sync')
        def sync():
            git.pull()
            return {'ok': True}

        @app.post('/api/webhook')
        def webhook():
            if config.webhook_secret and not _valid_signature(
                config.webhook_secret, request.get_data(), request.headers.get('X-Hub-Signature-256')
            ):
                return {'ok': False}, 403
            git.pull()
            return {'ok': True}

    return app


def create_wsgi() -> Flask:
    return create_app(Services.build(Config.default()))


def serve(port: int, all_interfaces: bool) -> None:
    services = Services.build(Config.default())
    for label, h in display_hosts(all_interfaces):
        print(f'http://{h}:{port}/' + (f'   ({label})' if label else ''))
    host = '0.0.0.0' if all_interfaces else display_hosts(False)[0][1]
    create_app(services).run(host=host, port=port, threaded=True)
