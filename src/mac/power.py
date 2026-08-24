import subprocess

HOLD_BATT = {'sleep': '0', 'standby': '0', 'powernap': '0'}


def on_ac() -> bool:
    try:
        out = subprocess.run(
            ['pmset', '-g', 'batt'], capture_output=True, text=True, timeout=2
        ).stdout
        return 'AC Power' in out
    except Exception:
        return False


def batt_get() -> dict[str, str]:
    try:
        text = subprocess.run(
            ['pmset', '-g', 'custom'], capture_output=True, text=True, timeout=5
        ).stdout
    except Exception:
        return {}
    out, in_batt = {}, False
    for line in text.splitlines():
        if line.startswith('Battery Power:'):
            in_batt = True
            continue
        if line and not line[0].isspace():
            in_batt = False
        if in_batt:
            parts = line.split()
            if len(parts) >= 2:
                out[parts[0]] = parts[1]
    return out


def sudo_disable_sleep() -> None:
    subprocess.run(['sudo', 'pmset', '-a', 'disablesleep', '1'], check=False)


class Hold:
    def __init__(self) -> None:
        self._orig = batt_get()
        self._caff: list[subprocess.Popen] = []

    def acquire(self) -> None:
        subprocess.run(['pmset', '-a', 'disablesleep', '1'], check=False)
        for k, v in HOLD_BATT.items():
            subprocess.run(['pmset', '-b', k, v], check=False)
        if not self._caff or self._caff[0].poll() is not None:
            self._caff[:] = [subprocess.Popen(['caffeinate', '-is'], stdin=subprocess.DEVNULL)]

    def release(self) -> None:
        subprocess.run(['pmset', '-a', 'disablesleep', '0'], check=False)
        for k in HOLD_BATT:
            if k in self._orig:
                subprocess.run(['pmset', '-b', k, self._orig[k]], check=False)
        if self._caff and self._caff[0].poll() is None:
            self._caff[0].terminate()
        self._caff.clear()
