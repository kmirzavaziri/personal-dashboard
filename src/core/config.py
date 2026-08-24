import os
from dataclasses import dataclass
from pathlib import Path


def _flag(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


@dataclass(frozen=True)
class Config:
    repo_root: Path
    src: Path
    main: Path
    templates: Path
    db: Path
    storage: Path
    images: Path
    health_db: Path
    styling_db: Path
    expenses_db: Path

    data_dir: Path
    data_repo: str | None
    git_backup: bool
    git_push_debounce: float
    git_branch: str
    enable_mac: bool
    mac_host: str | None
    allowed_email: str | None
    mcp_token: str | None
    webhook_secret: str | None
    cf_proxy_secret: str | None
    web_hosts: tuple[str, ...]
    git_sha: str | None

    @classmethod
    def default(cls) -> 'Config':
        return cls.from_env()

    @classmethod
    def from_env(cls, env: dict | None = None) -> 'Config':
        env = os.environ if env is None else env
        src = Path(__file__).parent.parent
        repo_root = src.parent
        db = Path(env.get('DB_ROOT') or repo_root / 'db').expanduser()
        storage = Path(env.get('STORAGE_ROOT') or repo_root / 'storage').expanduser()
        data_repo = env.get('DATA_REPO') or None
        return cls(
            repo_root=repo_root,
            src=src,
            main=repo_root / 'main.py',
            templates=src / 'core' / 'web' / 'templates',
            db=db,
            storage=storage,
            images=storage / 'images',
            health_db=db / 'health',
            styling_db=db / 'styling',
            expenses_db=db / 'expenses',
            data_dir=Path(env.get('DATA_DIR') or db.parent).expanduser(),
            data_repo=data_repo,
            git_backup=_flag(env.get('GIT_BACKUP'), bool(data_repo)),
            git_push_debounce=float(env.get('GIT_PUSH_DEBOUNCE') or 5.0),
            git_branch=env.get('GIT_BRANCH') or 'main',
            enable_mac=_flag(env.get('ENABLE_MAC'), True),
            mac_host=env.get('MAC_HOST') or None,
            allowed_email=env.get('ALLOWED_EMAIL') or None,
            mcp_token=env.get('MCP_TOKEN') or None,
            webhook_secret=env.get('WEBHOOK_SECRET') or None,
            cf_proxy_secret=env.get('CF_PROXY_SECRET') or None,
            web_hosts=tuple(h.strip() for h in (env.get('WEB_HOSTS') or '').split(',') if h.strip()),
            git_sha=env.get('RENDER_GIT_COMMIT') or env.get('GIT_SHA') or None,
        )
