import base64
import hashlib
import hmac
import json
import time
from urllib.parse import quote

from flask import Blueprint, jsonify, redirect, request

_CODE_TTL = 300
_TOKEN_TTL = 30 * 24 * 3600
_REFRESH_TTL = 365 * 24 * 3600
_PUBLIC_PREFIXES = ('/.well-known/', '/oauth/')


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))


def _signing_key(secret: str) -> bytes:
    return hashlib.sha256(f'oauth-sign:{secret}'.encode()).digest()


def _sign(key: bytes, payload: dict) -> str:
    body = _b64e(json.dumps(payload, separators=(',', ':'), sort_keys=True).encode())
    sig = _b64e(hmac.new(key, body.encode(), hashlib.sha256).digest())
    return f'{body}.{sig}'


def _unsign(key: bytes, token: str) -> dict | None:
    try:
        body, sig = token.split('.', 1)
    except ValueError:
        return None
    expected = _b64e(hmac.new(key, body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_b64d(body))
    except (ValueError, TypeError):
        return None
    exp = payload.get('exp')
    if exp is not None and time.time() > exp:
        return None
    return payload


def _base_url(config) -> str:
    if config.mcp_public_url:
        return config.mcp_public_url.rstrip('/')
    scheme = request.headers.get('X-Forwarded-Proto') or request.scheme
    return f'{scheme}://{request.host}'


def resource_metadata_url(config) -> str:
    return f'{_base_url(config)}/.well-known/oauth-protected-resource'


def is_public_path(path: str) -> bool:
    return path.startswith(_PUBLIC_PREFIXES)


def valid_access_token(config, header: str) -> bool:
    if not config.oauth_client_secret:
        return False
    if not header or not header.startswith('Bearer '):
        return False
    payload = _unsign(_signing_key(config.oauth_client_secret), header[7:])
    return bool(payload) and payload.get('typ') == 'access'


def _metadata(config) -> dict:
    base = _base_url(config)
    return {
        'issuer': base,
        'authorization_endpoint': f'{base}/oauth/authorize',
        'token_endpoint': f'{base}/oauth/token',
        'response_types_supported': ['code'],
        'grant_types_supported': ['authorization_code', 'refresh_token'],
        'code_challenge_methods_supported': ['S256'],
        'token_endpoint_auth_methods_supported': ['client_secret_post', 'client_secret_basic'],
        'scopes_supported': ['mcp'],
    }


def _resource_metadata(config) -> dict:
    base = _base_url(config)
    return {'resource': f'{base}/mcp', 'authorization_servers': [base]}


def _ok_redirect(uri: str) -> bool:
    return '://' in uri


def _client_creds() -> tuple[str | None, str | None]:
    header = request.headers.get('Authorization', '')
    if header.startswith('Basic '):
        try:
            client_id, _, secret = base64.b64decode(header[6:]).decode().partition(':')
            return client_id, secret
        except (ValueError, TypeError):
            return None, None
    return request.form.get('client_id'), request.form.get('client_secret')


def _secret_ok(provided, expected) -> bool:
    return bool(provided) and bool(expected) and hmac.compare_digest(provided, expected)


def _pkce_ok(verifier: str, challenge: str) -> bool:
    if not verifier or not challenge:
        return False
    digest = _b64e(hashlib.sha256(verifier.encode()).digest())
    return hmac.compare_digest(digest, challenge)


def _redirect_with(redirect_uri: str, state: str | None, **params) -> object:
    query = '&'.join(f'{k}={quote(v)}' for k, v in params.items() if v)
    if state:
        query += f'&state={quote(state)}'
    sep = '&' if '?' in redirect_uri else '?'
    return redirect(f'{redirect_uri}{sep}{query}', code=302)


def _issue(key: bytes) -> dict:
    now = time.time()
    return {
        'access_token': _sign(key, {'typ': 'access', 'exp': now + _TOKEN_TTL}),
        'token_type': 'Bearer',
        'expires_in': _TOKEN_TTL,
        'refresh_token': _sign(key, {'typ': 'refresh', 'exp': now + _REFRESH_TTL}),
        'scope': 'mcp',
    }


def make_oauth_bp(config) -> Blueprint:
    bp = Blueprint('oauth', __name__)
    key = _signing_key(config.oauth_client_secret) if config.oauth_client_secret else b''

    @bp.get('/.well-known/oauth-authorization-server')
    def as_metadata():
        return jsonify(_metadata(config))

    @bp.get('/.well-known/openid-configuration')
    def openid_metadata():
        return jsonify(_metadata(config))

    @bp.get('/.well-known/oauth-protected-resource')
    def protected_resource():
        return jsonify(_resource_metadata(config))

    @bp.get('/oauth/authorize')
    def authorize():
        params = request.args
        state = params.get('state')
        if params.get('client_id') != config.oauth_client_id:
            return 'invalid client_id', 400
        redirect_uri = params.get('redirect_uri')
        if not redirect_uri or not _ok_redirect(redirect_uri):
            return 'invalid redirect_uri', 400
        if params.get('response_type') != 'code':
            return _redirect_with(redirect_uri, state, error='unsupported_response_type')
        challenge = params.get('code_challenge')
        if not challenge or params.get('code_challenge_method') != 'S256':
            return _redirect_with(redirect_uri, state, error='invalid_request')
        code = _sign(key, {'typ': 'code', 'exp': time.time() + _CODE_TTL,
                           'redirect_uri': redirect_uri, 'challenge': challenge})
        return _redirect_with(redirect_uri, state, code=code)

    @bp.post('/oauth/token')
    def token():
        client_id, client_secret = _client_creds()
        if client_id != config.oauth_client_id or not _secret_ok(client_secret, config.oauth_client_secret):
            return jsonify(error='invalid_client'), 401
        grant = request.form.get('grant_type')
        if grant == 'authorization_code':
            payload = _unsign(key, request.form.get('code', ''))
            if not payload or payload.get('typ') != 'code':
                return jsonify(error='invalid_grant'), 400
            if payload.get('redirect_uri') != request.form.get('redirect_uri', ''):
                return jsonify(error='invalid_grant'), 400
            if not _pkce_ok(request.form.get('code_verifier', ''), payload.get('challenge', '')):
                return jsonify(error='invalid_grant'), 400
            return jsonify(_issue(key))
        if grant == 'refresh_token':
            payload = _unsign(key, request.form.get('refresh_token', ''))
            if not payload or payload.get('typ') != 'refresh':
                return jsonify(error='invalid_grant'), 400
            return jsonify(_issue(key))
        return jsonify(error='unsupported_grant_type'), 400

    return bp
