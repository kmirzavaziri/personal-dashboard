import json
import os
import plistlib
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.mcp_client import MCPClient
from messaging import imessage

LABEL = 'dashboard.messaging-relay'
PLIST = Path.home() / 'Library' / 'LaunchAgents' / f'{LABEL}.plist'
LOG = Path.home() / 'Library' / 'Logs' / f'{LABEL}.log'
STATE = Path.home() / 'Library' / 'Application Support' / 'dashboard' / f'{LABEL}.json'
_BATCH_SIZE = 50
_SYNC_INTERVAL_SECONDS = 3600
_THROTTLE_SECONDS = 60
_SENDERS_MAX_AGE = timedelta(hours=1)


@dataclass
class RelayState:
    since: str
    last_row_id: int = 0
    senders: list[str] = field(default_factory=list)
    senders_fetched_at: str = ''
    last_sync: str = ''
    last_outcome: dict = field(default_factory=dict)
    last_error: str = ''

    @classmethod
    def load(cls) -> 'RelayState | None':
        return cls(**json.loads(STATE.read_text())) if STATE.exists() else None

    def save(self) -> None:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(asdict(self), indent=2))

    def senders_stale(self, now: datetime) -> bool:
        return not self.senders_fetched_at or now - datetime.fromisoformat(self.senders_fetched_at) > _SENDERS_MAX_AGE


def start_of_day(day: str) -> str:
    return datetime.fromisoformat(day).replace(tzinfo=timezone.utc).isoformat()


def sync(client: MCPClient, state: RelayState) -> Counter:
    now = datetime.now(timezone.utc)
    if state.senders_stale(now):
        state.senders = client.call_json('messaging_senders')
        state.senders_fetched_at = now.isoformat()
    messages = imessage.received(state.senders, state.last_row_id, datetime.fromisoformat(state.since))
    outcome = Counter()
    for first in range(0, len(messages), _BATCH_SIZE):
        batch = messages[first:first + _BATCH_SIZE]
        outcome.update(_forward(client, batch))
        state.last_row_id = batch[-1].row_id
        state.save()
    state.last_sync, state.last_outcome, state.last_error = now.isoformat(), dict(outcome), ''
    state.save()
    return outcome


def _forward(client: MCPClient, messages: list[imessage.Message]) -> Counter:
    outcome = Counter()
    for first in range(0, len(messages), _BATCH_SIZE):
        batch = messages[first:first + _BATCH_SIZE]
        outcome.update(client.call_json('messaging_ingest', source='sms', messages=[m.as_payload() for m in batch]))
    return outcome


def import_backup(client: MCPClient, since: str) -> Counter:
    senders = client.call_json('messaging_senders')
    return _forward(client, imessage.received(senders, 0, datetime.fromisoformat(since), imessage.latest_iphone_backup()))


def preview(senders: list[str], since: str) -> Counter:
    messages = imessage.received(senders, 0, datetime.fromisoformat(since))
    return Counter((message.sender, f'{message.sent_at:%Y-%m}') for message in messages)


def _domain() -> str:
    return f'gui/{os.getuid()}'


def _launch_agent(config) -> dict:
    return {
        'Label': LABEL,
        'ProgramArguments': [sys.executable, str(config.main), 'messaging', 'relay', 'sync'],
        'EnvironmentVariables': {
            'DASHBOARD_API_URL': config.dashboard_api_url,
            'DASHBOARD_API_TOKEN': config.dashboard_api_token or '',
        },
        'RunAtLoad': True,
        'KeepAlive': {'SuccessfulExit': False},
        'StartInterval': _SYNC_INTERVAL_SECONDS,
        'WatchPaths': [str(imessage.CHAT_DB_WAL)],
        'ThrottleInterval': _THROTTLE_SECONDS,
        'StandardOutPath': str(LOG),
        'StandardErrorPath': str(LOG),
    }


def install(config) -> None:
    if not config.dashboard_api_url or not config.dashboard_api_token:
        raise SystemExit('Set DASHBOARD_API_URL and DASHBOARD_API_TOKEN before starting the relay')
    uninstall()
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with PLIST.open('wb') as f:
        plistlib.dump(_launch_agent(config), f)
    PLIST.chmod(0o600)
    if subprocess.run(['launchctl', 'bootstrap', _domain(), str(PLIST)], capture_output=True).returncode != 0:
        subprocess.run(['launchctl', 'load', '-w', str(PLIST)], check=True, capture_output=True)
    subprocess.run(['launchctl', 'kickstart', f'{_domain()}/{LABEL}'], check=True, capture_output=True)


def uninstall() -> None:
    if subprocess.run(['launchctl', 'bootout', f'{_domain()}/{LABEL}'], capture_output=True).returncode != 0 \
            and PLIST.exists():
        subprocess.run(['launchctl', 'unload', str(PLIST)], capture_output=True)
    PLIST.unlink(missing_ok=True)


def is_running() -> bool:
    return LABEL in subprocess.run(['launchctl', 'list'], capture_output=True, text=True).stdout


def interpreter() -> str:
    return os.path.realpath(sys.executable)
