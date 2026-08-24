import socket
import subprocess
import time
from contextlib import suppress


def host() -> str:
    try:
        out = subprocess.run(
            ['tailscale', 'ip', '-4'], capture_output=True, text=True, timeout=2
        ).stdout.strip().splitlines()
        if out and out[0]:
            return out[0]
    except Exception:
        pass
    return 'localhost'


def lan_ip() -> str:
    for iface in ('en0', 'en1'):
        with suppress(Exception):
            out = subprocess.run(
                ['ipconfig', 'getifaddr', iface], capture_output=True, text=True, timeout=2
            ).stdout.strip()
            if out:
                return out
    with suppress(Exception):
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect(('8.8.8.8', 80))
        ip = probe.getsockname()[0]
        probe.close()
        return ip
    return 'localhost'


def display_hosts(all_interfaces: bool) -> list[tuple[str, str]]:
    if all_interfaces:
        return [('wifi/LAN', lan_ip()), ('tailscale', host())]
    return [('', host())]


def wait_port(h: str, port: int, timeout: float) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        with suppress(OSError):
            with socket.create_connection((h, port), timeout=0.5):
                return True
        time.sleep(0.1)
    return False
