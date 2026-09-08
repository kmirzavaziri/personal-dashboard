import subprocess
import threading
from datetime import datetime
from pathlib import Path


class GitData:
    def __init__(self, root: Path, branch: str = 'main', debounce: float = 5.0):
        self.root = Path(root)
        self.branch = branch
        self.debounce = debounce
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    def _git(self, *args: str, timeout: float = 25.0) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                ['git', '-C', str(self.root), *args],
                capture_output=True, text=True, check=False, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(args, 1, '', 'timeout')

    def pull(self) -> str:
        with self._lock:
            result = self._git('pull', '--ff-only', 'origin', self.branch)
            return (result.stdout + result.stderr).strip()[-400:] or 'up to date'

    def mark_dirty(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce, self.flush)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> str:
        with self._lock:
            self._timer = None
            self._git('add', '-A')
            status = self._git('status', '--porcelain').stdout.strip()
            if not status:
                return 'nothing to commit'
            count = len(status.splitlines())
            self._git('commit', '-m', f'data: {datetime.now():%Y-%m-%d %H:%M:%S}')
            push = self._git('push', 'origin', self.branch)
            if push.returncode != 0:
                return f'committed {count} file(s), push FAILED: {push.stderr.strip()[-300:]}'
            return f'pushed {count} file(s)'
