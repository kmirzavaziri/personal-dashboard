from pathlib import Path

import training.service as training
from core.web.templating import make_env, trim_number

HERE = Path(__file__).parent

_jinja = make_env(HERE)
_jinja.filters['kg'] = trim_number


def render(services) -> str:
    return _jinja.get_template('training.html').render(plan=training.plan(services.config))
