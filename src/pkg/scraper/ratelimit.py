import fcntl
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RateLimiter:
    lock_path: Path
    min_interval: float
    max_per_window: int
    window_seconds: float

    def wait(self) -> None:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, 'a+') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.seek(0)
            raw = handle.read().strip()
            recent = json.loads(raw) if raw else []
            if not isinstance(recent, list):
                recent = []
            now = time.time()
            recent = [t for t in recent if now - t < self.window_seconds]
            delay = 0.0
            if recent:
                delay = max(delay, self.min_interval - (now - recent[-1]))
            if len(recent) >= self.max_per_window:
                delay = max(delay, self.window_seconds - (now - recent[0]) + 1)
            if delay > 0:
                print(
                    f'  ⏳ rate limit: waiting {delay:.0f}s '
                    f'({len(recent)}/{self.max_per_window} used this {self.window_seconds / 60:.0f}m window)…',
                    file=sys.stderr, flush=True,
                )
                time.sleep(delay)
            now = time.time()
            recent.append(now)
            recent = [t for t in recent if now - t < self.window_seconds]
            handle.seek(0)
            handle.truncate()
            handle.write(json.dumps(recent))
            fcntl.flock(handle, fcntl.LOCK_UN)
