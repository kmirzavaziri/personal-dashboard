import os
import signal
import subprocess
import sys
import time

from core.config import Config
from mac import power, procs, sessions, state

DEFAULT_TTL_MIN = 30
GRACE_SEC = 300
TICK_SEC = 10


def _set_deadline(minutes: int) -> None:
    state.STATE.write('deadline', str(int(time.time()) + minutes * 60))
    state.STATE.write('command', 'none')


def extend(minutes: int) -> None:
    _set_deadline(minutes)


def sleep_now() -> None:
    state.STATE.write('command', 'off')


def status() -> dict:
    deadline = state.STATE.read('deadline')
    command = state.STATE.read('command')
    alive = state.controller_alive()
    now = int(time.time())
    active = sessions.sessions()
    remaining = (int(deadline) - now) if deadline else 0
    working = any(s['working'] for s in active)
    grace_floor = 0
    if active:
        newest = now - min(s['age'] for s in active)
        grace_floor = newest + GRACE_SEC
    sleep_in = max(int(deadline) if deadline else 0, grace_floor) - now
    return {
        'on': alive and command != 'off',
        'alive': alive,
        'command': command or 'none',
        'remaining': max(0, remaining),
        'working': working,
        'sleep_in': max(0, sleep_in),
        'power': 'ac' if power.on_ac() else 'battery',
        'sessions': active,
        'sockets': sessions.sockets(),
        'ttyd_port': procs.TTYD_PORT,
    }


def status_text() -> None:
    s = status()
    if s['on']:
        print(f"mac: awake  (ttl {s['remaining']}s remaining, on {s['power']})")
    else:
        print(f"mac: released  (on {s['power']})")
    print(f"  sessions: {len(s['sessions'])}")


def arm(config: Config, minutes: int) -> None:
    sessions.ACTIVITY_DIR.mkdir(parents=True, exist_ok=True)
    sessions.SOCK_DIR.mkdir(parents=True, exist_ok=True)
    state.STATE.clear()
    _set_deadline(minutes)

    power.sudo_disable_sleep()

    if not state.controller_alive():
        state.PIDFILE.unlink(missing_ok=True)
        with state.LOG.open('a') as log:
            subprocess.Popen(
                ['sudo', 'nohup', sys.executable, str(config.main), 'mac', 'controller'],
                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            )
        for _ in range(50):
            if state.controller_alive():
                break
            time.sleep(0.1)
        else:
            raise SystemExit(f'keep-awake controller failed to start — see {state.LOG}')

    procs.start_ttyd(config)


def controller_loop() -> None:
    state.PIDFILE.write_text(str(os.getpid()))
    hold = power.Hold()

    def cleanup(*_):
        hold.release()
        state.PIDFILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    held = True
    hold.acquire()

    while state.STATE.exists():
        command = state.STATE.read('command')
        deadline = state.STATE.read('deadline')
        now = int(time.time())
        keep = False
        if command != 'off':
            working, last = sessions.session_working()
            if deadline and now < int(deadline):
                keep = True
            if working:
                keep = True
            if now < last + GRACE_SEC:
                keep = True
        if keep and not held:
            hold.acquire()
            held = True
        elif not keep and held:
            hold.release()
            held = False
        time.sleep(TICK_SEC)

    cleanup()
