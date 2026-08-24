import os
import signal
import time
from contextlib import suppress
from pathlib import Path

class State:
    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.exists()

    def clear(self) -> None:
        self.path.write_text('')

    def read(self, key: str) -> str | None:
        if not self.path.exists():
            return None
        value = None
        for line in self.path.read_text().splitlines():
            if line.startswith(key + '='):
                value = line[len(key) + 1:]
        return value

    def write(self, key: str, value: str) -> None:
        lines = []
        if self.path.exists():
            lines = [l for l in self.path.read_text().splitlines() if not l.startswith(key + '=')]
        lines.append(f'{key}={value}')
        self.path.write_text('\n'.join(lines) + '\n')


STATE = State(Path('/tmp/mac.state'))
PIDFILE = Path('/tmp/mac-controller.pid')
TTYD_PIDFILE = Path('/tmp/mac-ttyd.pid')
SERVER_PIDFILE = Path('/tmp/personal-server.pid')
LOG = Path('/tmp/mac.log')


def read_pid(path: Path) -> int | None:
    try:
        return int(path.read_text())
    except Exception:
        return None


def pid_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False
    return True


def controller_alive() -> bool:
    return pid_alive(read_pid(PIDFILE))


def stop_pid(pidfile: Path) -> None:
    pid = read_pid(pidfile)
    if pid:
        with suppress(Exception):
            os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            if not pid_alive(pid):
                break
            time.sleep(0.1)
    pidfile.unlink(missing_ok=True)
