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
            result = self._git('pull', '--no-rebase', '--no-edit', 'origin', self.branch)
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
            if status:
                self._git('commit', '-m', f'data: {datetime.now():%Y-%m-%d %H:%M:%S}')
            elif not self._unpushed():
                return 'nothing to commit'
            return self._push()

    def _unpushed(self) -> bool:
        return self._git('rev-list', '--count', f'origin/{self.branch}..HEAD').stdout.strip() not in ('', '0')

    def _push(self) -> str:
        if self._git('push', 'origin', self.branch).returncode == 0:
            return 'pushed'
        merge = self._git('pull', '--no-rebase', '--no-edit', '-X', 'ours', 'origin', self.branch)
        if merge.returncode != 0:
            self._git('merge', '--abort')
            return f'push FAILED, merge with origin failed: {(merge.stdout + merge.stderr).strip()[-400:]}'
        push = self._git('push', 'origin', self.branch)
        if push.returncode != 0:
            return f'push FAILED after merging origin: {push.stderr.strip()[-300:]}'
        return 'merged origin and pushed'
