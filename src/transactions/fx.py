import json
import urllib.request
from functools import cache
from urllib.error import URLError

from pkg.model.io import read_yaml

BASE = 'AED'
_LATEST_API = 'https://open.er-api.com/v6/latest/{currency}'


def _pegs(config):
    return (read_yaml(config.db / 'transactions' / 'fx.yaml') or {}).get('pegs') or {}


@cache
def _fetch(currency, day):
    try:
        with urllib.request.urlopen(_LATEST_API.format(currency=currency), timeout=10) as resp:
            return json.loads(resp.read()).get('rates', {}).get(BASE)
    except (URLError, ValueError, TimeoutError):
        return None


def rate(config, currency, day):
    if not currency or currency == BASE:
        return 1.0
    return _pegs(config).get(currency) or _fetch(currency, day)
