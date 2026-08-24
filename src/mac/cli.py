import os
import re
import subprocess
import time

import typer

from mac import controller, net, procs, sessions

mac_app = typer.Typer(no_args_is_help=True, add_completion=False, help='Keep-awake controller + session launcher')
server_app = typer.Typer(no_args_is_help=True, add_completion=False, help='Dashboard + phone terminal servers')


def register(root: typer.Typer) -> None:
    root.add_typer(server_app, name='server')
    root.add_typer(mac_app, name='mac')


@server_app.command(help='Start dashboard + terminal servers (detached).')
def up(
    ctx: typer.Context,
    port: int = typer.Option(8080, help='Dashboard port'),
    all_interfaces: bool = typer.Option(False, '--all', help='Expose on all network interfaces (0.0.0.0), not just Tailscale/localhost'),
):
    config = ctx.obj.config
    procs.stop_ttyd()
    procs.stop_server()
    procs.start_ttyd(config)
    procs.start_server(config, port, all_interfaces)
    for label, h in net.display_hosts(all_interfaces):
        print(f'http://{h}:{port}/' + (f'   ({label})' if label else ''))


@server_app.command(help='Stop dashboard + terminal servers.')
def down():
    procs.stop_server()
    procs.stop_ttyd()
    print('stopped')


@server_app.command(hidden=True, help='Run the dashboard in the foreground.')
def serve(
    port: int = typer.Option(8080, help='Port to listen on'),
    all_interfaces: bool = typer.Option(False, '--all', help='Bind to 0.0.0.0 (all network interfaces)'),
):
    from webapp import serve as _serve
    _serve(port, all_interfaces)


def _clear():
    print('\033[2J\033[3J\033[H', end='')


def _session_menu(sock_dir):
    while True:
        socks = sorted(sock_dir.glob('*.sock')) if sock_dir.exists() else []
        _clear()
        if not socks:
            print('No live sessions.')
            print("Start one on the Mac with 'dash mac run <command>' (e.g. dash mac run claude).")
            if input('[enter] refresh · [q] quit: ').strip() == 'q':
                return
            continue
        print('Live sessions:\n')
        for i, s in enumerate(socks, 1):
            meta = s.with_suffix('.meta')
            name = meta.read_text().strip() if meta.exists() else s.stem
            print(f'  {i}) {name}')
        print()
        choice = input('pick number · [r] refresh · [q] quit: ').strip()
        if choice == 'q':
            return
        if choice == 'r':
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(socks):
            sock = socks[int(choice) - 1]
            _clear()
            print(f'Attaching to {sock.stem} — detach with Ctrl-\\')
            subprocess.run(['dtach', '-a', str(sock)])


@mac_app.command(help='Show the live-session picker (used by the web terminal).')
def attach(label: str = typer.Argument('', help='Session label to attach to; omit for the picker')):
    if label and re.fullmatch(r'[A-Za-z0-9_.-]+', label):
        sock = sessions.SOCK_DIR / f'{label}.sock'
        if sock.is_socket():
            print(f'Attaching to {label} — detach with Ctrl-\\')
            os.execvp('dtach', ['dtach', '-a', str(sock)])
        print(f"No live session '{label}'.")
        time.sleep(2)
    _session_menu(sessions.SOCK_DIR)


@mac_app.command(help='Arm the keep-awake controller (default 30m).')
def awake(ctx: typer.Context, minutes: int = typer.Argument(None, help='Minutes to stay awake')):
    controller.arm(ctx.obj.config, minutes if minutes is not None else controller.DEFAULT_TTL_MIN)
    print('done')


@mac_app.command(help='Release the keep-awake hold and let the Mac sleep.')
def release():
    controller.sleep_now()
    print('released')


@mac_app.command(help='Print keep-awake status.')
def status():
    controller.status_text()


@mac_app.command(name='run', help='Run a command inside a dtach session: dash mac run <command> [args...].',
                 context_settings={'allow_extra_args': True, 'ignore_unknown_options': True})
def mac_run(ctx: typer.Context):
    sessions.run(list(ctx.args))


@mac_app.command(name='controller', hidden=True)
def run_controller():
    controller.controller_loop()
