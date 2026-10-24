from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from core.item.status import statuses

_BASE_TEMPLATES = Path(__file__).parent / 'templates'
DIRHAM = Markup('<span class="dh" role="img" aria-label="AED"></span>')


def trim_number(value: float) -> str:
    return f'{value:.1f}'.rstrip('0').rstrip('.')


def make_env(template_dir: Path) -> Environment:
    env = Environment(
        loader=FileSystemLoader([str(template_dir), str(_BASE_TEMPLATES)]),
        autoescape=True,
    )
    env.globals['statuses'] = statuses
    env.globals['dh'] = DIRHAM
    return env
