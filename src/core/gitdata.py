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

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ['git', '-C', str(self.root), *args],
            capture_output=True, text=True, check=False,
        )

    def pull(self) -> None:
        with self._lock:
            self._git('pull', '--ff-only', 'origin', self.branch)

    def mark_dirty(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.debounce, self.flush)
            self._timer.daemon = True
            self._timer.start()

    def flush(self) -> None:
        with self._lock:
            self._timer = None
            self._git('add', '-A')
            if not self._git('status', '--porcelain').stdout.strip():
                return
            self._git('commit', '-m', f'data: {datetime.now():%Y-%m-%d %H:%M:%S}')
            self._git('push', 'origin', self.branch)
