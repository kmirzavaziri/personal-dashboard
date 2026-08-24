from pathlib import Path

from core.web.templating import make_env
from mac.procs import TTYD_PORT
from mac.sessions import session_name

HERE = Path(__file__).parent


def render(services) -> str:
    env = make_env(HERE)
    return env.get_template('mac.html').render(ttyd_port=TTYD_PORT)


def render_term(sock: str) -> str:
    env = make_env(HERE)
    return env.get_template('term.html').render(
        ttyd_port=TTYD_PORT, sock=sock, name=session_name(sock) if sock else '',
    )
