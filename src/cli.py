import importlib
import sys

import typer

from core.config import Config
from core.services import Services
from health import cli as health_cli
from mac import cli as mac_cli
from styling import cli as styling_cli
from core.store import cli as store_cli

_PAGES = {
    'health':   'health.view',
    'shopping': 'shopping_list.view',
    'styling':  'styling.view',
    'expenses': 'expenses.view',
    'mac':      'mac.view',
    'planner':  'planner.view',
    'calendar': 'agenda.view',
}

app = typer.Typer(no_args_is_help=True, add_completion=False, help='Personal dashboard CLI')


@app.callback()
def main(ctx: typer.Context):
    ctx.obj = Services.build(Config.default())


mac_cli.register(app)
health_cli.register(app)
store_cli.register(app)
styling_cli.register(app)


def check(ctx: typer.Context, page: str = typer.Argument('all', help="Page to check, or 'all'")):
    if page != 'all' and page not in _PAGES:
        raise SystemExit(f"Unknown page '{page}'. Choose from: all, {', '.join(_PAGES)}")
    services = ctx.obj
    pages = list(_PAGES.items()) if page == 'all' else [(page, _PAGES[page])]
    ok = True
    for name, module_path in pages:
        try:
            mod = importlib.import_module(module_path)
            html = mod.render(services)
            print(f'  {name:<8} OK  ({len(html):,} chars)')
        except Exception as exc:
            print(f'  {name:<8} ERROR  {exc}')
            ok = False
    if not ok:
        sys.exit(1)


app.command(help='Smoke-test pages — verifies they render without errors.')(check)

__all__ = ('app',)
