import shutil
import subprocess
import sys

from core.config import Config
from mac import net, state
from mac.sessions import SOCK_DIR

TTYD_PORT = 7681
TTYD_FONT_SIZE = 13
STARTUP_WAIT_SEC = 5.0


def start_ttyd(config: Config) -> None:
    if not shutil.which('ttyd'):
        print('  ttyd not installed — phone terminal disabled (brew install ttyd)')
        return
    if state.pid_alive(state.read_pid(state.TTYD_PIDFILE)):
        return
    SOCK_DIR.mkdir(parents=True, exist_ok=True)
    h = net.host()
    with state.LOG.open('a') as log:
        p = subprocess.Popen(
            ['ttyd', '-p', str(TTYD_PORT), '-i', h, '-W', '-a',
             '-t', f'fontSize={TTYD_FONT_SIZE}',
             '-t', 'theme={"background":"#0f0f0f","foreground":"#d4d4d4"}',
             sys.executable, str(config.main), 'mac', 'attach'],
            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    state.TTYD_PIDFILE.write_text(str(p.pid))
    if not net.wait_port(h, TTYD_PORT, STARTUP_WAIT_SEC):
        raise SystemExit(f'ttyd failed to start on {h}:{TTYD_PORT} — see {state.LOG}')


def stop_ttyd() -> None:
    state.stop_pid(state.TTYD_PIDFILE)


def start_server(config: Config, port: int, all_interfaces: bool) -> None:
    if state.pid_alive(state.read_pid(state.SERVER_PIDFILE)):
        return
    args = [sys.executable, str(config.main), 'server', 'serve', '--port', str(port)]
    if all_interfaces:
        args.append('--all')
    with state.LOG.open('a') as log:
        p = subprocess.Popen(
            args,
            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            start_new_session=True, cwd=str(config.main.parent),
        )
    state.SERVER_PIDFILE.write_text(str(p.pid))
    probe_host = '127.0.0.1' if all_interfaces else net.host()
    if not net.wait_port(probe_host, port, STARTUP_WAIT_SEC):
        raise SystemExit(f'dashboard failed to start on {probe_host}:{port} — see {state.LOG}')


def stop_server() -> None:
    state.stop_pid(state.SERVER_PIDFILE)
