from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from core.item.status import status_config

_BASE_TEMPLATES = Path(__file__).parent / 'templates'


def trim_number(value: float) -> str:
    return f'{value:.1f}'.rstrip('0').rstrip('.')


def make_env(template_dir: Path) -> Environment:
    env = Environment(
        loader=FileSystemLoader([str(template_dir), str(_BASE_TEMPLATES)]),
        autoescape=True,
    )
    env.globals['status_config'] = status_config
    return env
