import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent
_HOOK = HERE / 'claude-activity-hook'
_HOOK_EVENTS = (
    'UserPromptSubmit', 'PreToolUse', 'PostToolUse', 'PostToolUseFailure',
    'SubagentStart', 'SubagentStop', 'PreCompact', 'PermissionRequest', 'Stop', 'SessionEnd',
)


def _hooks_settings() -> Path:
    entry = [{'matcher': '*', 'hooks': [{'type': 'command', 'command': str(_HOOK)}]}]
    settings = {'hooks': {event: entry for event in _HOOK_EVENTS}}
    path = Path(tempfile.gettempdir()) / 'dashboard-claude-hooks.json'
    path.write_text(json.dumps(settings))
    return path

ACTIVITY_DIR = Path('/tmp/claude-activity')
SOCK_DIR = Path('/tmp/claude')

CAP_SEC = 1200

KEYS = {
    'enter': b'\r',
    'esc': b'\x1b',
    'tab': b'\t',
    'shift-tab': b'\x1b[Z',
    'ctrl-c': b'\x03',
    'ctrl-d': b'\x04',
    'ctrl-l': b'\x0c',
    'up': b'\x1b[A',
    'down': b'\x1b[B',
    'left': b'\x1b[D',
    'right': b'\x1b[C',
}

WORKING_EVENTS = {
    'UserPromptSubmit', 'PreToolUse', 'PostToolUse',
    'PostToolUseFailure', 'SubagentStart', 'SubagentStop',
    'PreCompact',
}


def claude_state(key: str) -> dict:
    idle = {'event': 'idle', 'age': 0, 'working': False}
    try:
        event, ts = (ACTIVITY_DIR / key).read_text().split()
        ts = int(ts)
    except Exception:
        return idle
    age = int(time.time()) - ts
    return {'event': event, 'age': age, 'working': event in WORKING_EVENTS and age < CAP_SEC}


def sessions() -> list[dict]:
    out = []
    now = int(time.time())
    if not SOCK_DIR.exists():
        return out
    for s in sorted(SOCK_DIR.glob('*.sock')):
        meta = s.with_suffix('.meta')
        cmd = meta.read_text().strip() if meta.exists() else s.stem
        first = Path(cmd.split(' ', 1)[0]).name if cmd else ''
        if first == 'claude':
            out.append({'id': cmd, 'sock': s.stem, **claude_state(s.stem)})
        else:
            out.append({
                'id': cmd,
                'sock': s.stem,
                'event': first or 'run',
                'age': now - int(s.stat().st_mtime),
                'working': True,
            })
    return out


def session_name(sock: str) -> str:
    meta = SOCK_DIR / f'{sock}.meta'
    if meta.exists():
        return meta.read_text().strip() or sock
    return sock


def sockets() -> list[str]:
    if not SOCK_DIR.exists():
        return []
    return [p.name[:-5] for p in sorted(SOCK_DIR.glob('*.sock'))]


def session_working() -> tuple[bool, int]:
    now = int(time.time())
    last = 0
    working = False
    if ACTIVITY_DIR.exists():
        for f in ACTIVITY_DIR.iterdir():
            try:
                event, ts = f.read_text().split()
                ts = int(ts)
            except Exception:
                continue
            if ts > last:
                last = ts
            if now - ts < CAP_SEC and event in WORKING_EVENTS:
                working = True
    if SOCK_DIR.exists():
        for s in SOCK_DIR.glob('*.sock'):
            meta = s.with_suffix('.meta')
            cmd = meta.read_text().strip() if meta.exists() else ''
            first = Path(cmd.split(' ', 1)[0]).name if cmd else ''
            if first == 'claude':
                continue
            working = True
            last = now
    return working, last


def send_key(sock: str, name: str) -> bool:
    data = KEYS.get(name)
    if data is None:
        return False
    s = SOCK_DIR / f'{sock}.sock'
    if not s.is_socket():
        return False
    try:
        subprocess.run(['dtach', '-p', str(s)], input=data, timeout=3)
        return True
    except Exception:
        return False


def _prepare(argv: list[str], cwd: Path) -> tuple[Path, list[str], dict]:
    SOCK_DIR.mkdir(parents=True, exist_ok=True)
    base = Path(argv[0]).name
    label = re.sub(r'[^A-Za-z0-9_-]', '_', cwd.name) + '-' + base
    sock = SOCK_DIR / f'{label}-{int(time.time())}-{os.getpid()}.sock'
    sock.with_suffix('.meta').write_text(' '.join(argv))
    env = {}
    if base == 'claude':
        env['MAC_SESSION'] = sock.stem
        cmd = ['claude', '--settings', str(_hooks_settings()), *argv[1:]]
    elif shutil.which(argv[0]):
        cmd = argv
    else:
        cmd = ['zsh', '-ic', shlex.join(argv)]
    return sock, cmd, env


def run(argv: list[str]) -> None:
    if not argv:
        raise SystemExit('usage: mac run <command> [args...]')
    if not shutil.which('dtach'):
        os.execvp(argv[0], argv)
    sock, cmd, env = _prepare(argv, Path.cwd())
    os.environ.update(env)
    os.execvp('dtach', ['dtach', '-A', str(sock), *cmd])


def start(argv: list[str], cwd: Path) -> str:
    if not shutil.which('dtach'):
        raise ValueError('dtach not installed')
    sock, cmd, env = _prepare(argv, cwd)
    subprocess.Popen(
        ['dtach', '-n', str(sock), *cmd],
        cwd=str(cwd), env={**os.environ, **env},
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return sock.stem


def start_command(command: str, cwd: str = '') -> str:
    argv = shlex.split(command)
    if not argv:
        raise ValueError('empty command')
    directory = Path(cwd).expanduser() if cwd else Path.home()
    if not directory.is_dir():
        raise ValueError(f'not a directory: {directory}')
    return start(argv, directory)
