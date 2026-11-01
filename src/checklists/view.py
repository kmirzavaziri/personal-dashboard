from pathlib import Path

from checklists.model import Checklist
from core.web.templating import make_env

HERE = Path(__file__).parent

_jinja = make_env(HERE)


def render(services) -> str:
    checklists = sorted(Checklist.objects.all(), key=lambda checklist: checklist.order)
    return _jinja.get_template('checklists.html').render(checklists=checklists)
