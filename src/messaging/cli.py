import sqlite3
from datetime import date

import typer

from core.mcp_client import MCPClient, MCPError
from messaging import relay

messaging_app = typer.Typer(no_args_is_help=True, add_completion=False, help='Messages forwarded to the dashboard')
relay_app = typer.Typer(no_args_is_help=True, add_completion=False,
                        help='Mac relay: forwards bank texts from the Messages app to the dashboard')

_SINCE_HELP = 'YYYY-MM-DD: forward messages sent on or after this day'


def register(root: typer.Typer) -> None:
    root.add_typer(messaging_app, name='messaging')
    messaging_app.add_typer(relay_app, name='relay')


def _state(since: str | None) -> relay.RelayState:
    state = relay.RelayState.load() or relay.RelayState(since=relay.start_of_day(since or date.today().isoformat()))
    if since:
        state.since = relay.start_of_day(since)
    return state


def _full_disk_access_hint() -> str:
    return (f'macOS blocked reading Messages. Grant Full Disk Access to {relay.interpreter()} in '
            f'System Settings → Privacy & Security → Full Disk Access, then run: dash messaging relay sync')


@relay_app.command(help='Install and start the background relay (runs at login, on new messages, and hourly).')
def start(ctx: typer.Context, since: str = typer.Option(None, help=f'{_SINCE_HELP} (first start: default today)')):
    _state(since).save()
    if relay.install(ctx.obj.config):
        print(f'relay started — logs: {relay.LOG}')
    else:
        print(f'relay installed at {relay.PLIST}; it starts at your next login, or run this command from '
              f'Terminal on this Mac to start it now (SSH sessions cannot start login items)')


@relay_app.command(help='Stop and uninstall the background relay.')
def stop():
    relay.uninstall()
    print('relay stopped')


@relay_app.command(help='Show whether the relay runs, how far it got, and its last result.')
def status():
    state = relay.RelayState.load()
    print(f"relay: {'running' if relay.is_running() else 'stopped'}")
    if state is None:
        print('never synced')
        return
    print(f'since: {state.since[:10]}   last message row: {state.last_row_id}')
    print(f"last sync: {state.last_sync or 'never'}   outcome: {state.last_outcome}")
    if state.last_error:
        print(f'last error: {state.last_error}')


@relay_app.command(help='Forward new messages now (what the background job runs).')
def sync(ctx: typer.Context, since: str = typer.Option(None, help=_SINCE_HELP)):
    state = _state(since)
    try:
        outcome = relay.sync(MCPClient.from_config(ctx.obj.config), state)
    except sqlite3.OperationalError:
        state.last_error = _full_disk_access_hint()
        state.save()
        raise SystemExit(state.last_error)
    except MCPError as exc:
        state.last_error = str(exc)
        state.save()
        raise SystemExit(state.last_error)
    print(dict(outcome) or 'nothing new')


@relay_app.command(help='Count the messages a sync would forward, per sender and month; sends nothing.')
def preview(ctx: typer.Context, since: str = typer.Option(..., help=_SINCE_HELP)):
    senders = MCPClient.from_config(ctx.obj.config).call_json('messaging_senders')
    counts = relay.preview(senders, relay.start_of_day(since))
    for (sender, month), count in sorted(counts.items()):
        print(f'{month}  {sender:<14} {count:>5}')
    print(f'total: {sum(counts.values())}')


@relay_app.command(name='import-backup',
                   help='Forward history from the newest unencrypted iPhone backup made by Finder; safe to re-run.')
def import_backup(ctx: typer.Context, since: str = typer.Option(..., help=_SINCE_HELP)):
    try:
        outcome = relay.import_backup(MCPClient.from_config(ctx.obj.config), relay.start_of_day(since))
    except FileNotFoundError as exc:
        raise SystemExit(f'{exc}. In Finder, select the iPhone, choose "Back up all of the data on your iPhone to '
                         f'this Mac" with "Encrypt local backup" off, click Back Up Now, then re-run.')
    except sqlite3.DatabaseError:
        raise SystemExit('The newest iPhone backup is encrypted. Make an unencrypted local backup in Finder and re-run.')
    print(dict(outcome) or 'nothing to import')
