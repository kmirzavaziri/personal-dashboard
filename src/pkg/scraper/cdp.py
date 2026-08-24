import socket
import subprocess
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import sync_playwright


@dataclass(frozen=True)
class CdpBrowser:
    chrome_path: str
    profile_dir: Path
    port: int

    @contextmanager
    def page(self):
        self._ensure_running()
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f'http://127.0.0.1:{self.port}')
            try:
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else context.new_page()
                agent = page.evaluate('() => navigator.userAgent').replace('HeadlessChrome', 'Chrome')
                context.new_cdp_session(page).send('Network.setUserAgentOverride', {'userAgent': agent})
                self._hide(browser, context, page)
                yield page
            finally:
                browser.close()

    def _hide(self, browser, context, page) -> None:
        target = context.new_cdp_session(page).send('Target.getTargetInfo')['targetInfo']['targetId']
        session = browser.new_browser_cdp_session()
        window = session.send('Browser.getWindowForTarget', {'targetId': target})['windowId']
        session.send('Browser.setWindowBounds', {'windowId': window, 'bounds': {'windowState': 'minimized'}})

    def _ensure_running(self) -> None:
        if self._port_open():
            return
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            [
                self.chrome_path,
                f'--remote-debugging-port={self.port}',
                f'--user-data-dir={self.profile_dir}',
                '--window-position=3000,3000',
                '--window-size=1200,900',
                '--disable-blink-features=AutomationControlled',
                '--no-first-run',
                '--no-default-browser-check',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self._await_port()

    def _port_open(self) -> bool:
        with suppress(OSError):
            socket.create_connection(('127.0.0.1', self.port), 0.5).close()
            return True
        return False

    def _await_port(self) -> None:
        for _ in range(80):
            if self._port_open():
                return
            time.sleep(0.25)
        raise RuntimeError(f'Chrome CDP port {self.port} did not open')
