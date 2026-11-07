"""The agent deny registry, REMOTE-WRITE-THROUGH-A-DOOR row -- pure DATA.

User ruling 2026-11-07: a write to a remote host goes through the door named for that host's kind --
:mod:`dev_lab.dev.hpcaccount` for a cluster account, :mod:`dev_lab.dev.opsserver` for a server the integrator
deploys -- both over the one transport :mod:`dev_lab.dev.remote`. A hand-written ``ssh`` that WRITES, and an
upload by ``scp``/``rsync``, are refused here; read-only ssh (``uptime``, ``systemctl status``, ``journalctl``,
``cat``, ``ls``, ``df``) stays open. HPC login hosts are refused whole by HPC-THROUGH-THE-DOOR, which fires first.

HOW A WRITE IS RECOGNISED: by the remote command's verb, from a closed list of the shapes that change a host
(:data:`_WRITERS`), and for a copy by its LAST argument being remote (``host:path``). A list rather than an
allowlist of readers because a refusal must name its exit, and a read the list misses is merely prompted.
"""

from __future__ import annotations

from dev_lab.dev.agentpolicy import exits_of
from dev_lab.dev.venvpath import PYTHON_SLOT

__all__ = ['REMOTE_WRITE']

_ID = 'REMOTE-WRITE-THROUGH-A-DOOR'

#: Remote verbs that change a host.
_WRITERS = (
    r'sudo|rm|mv|cp|tee|install|mkdir|rmdir|chmod|chown|ln|truncate|dd|kill|pkill|reboot|shutdown|crontab'
    r'|systemctl\s+(?:start|stop|restart|reload|enable|disable|daemon-reload|mask|edit)'
    r'|apt(?:-get)?|dnf|yum|pip3?|uv|git\s+(?:pull|push|checkout|switch|reset|merge|clone|fetch|clean|stash)'
    r'|docker\s+(?:run|rm|stop|start|restart|compose|pull|exec)|[\w./-]*python[\w.]*\s+-m\s+dev_lab\.ops'
)
#: ssh's options before its target: ``-o X``, ``-p 22``, ``-J jump``, ``-i key`` take a value; flags do not.
_SSH_OPTS = r'(?:\s+(?:-[oplJiFLRDwWcmbeEQS]\s*\S+|-[46AaCfGgKkMNnqsTtVvXxYy]+))*'

REMOTE_WRITE: dict[str, object] = {
    'id': _ID,
    'pattern': (
        rf'(?:ssh{_SSH_OPTS}\s+\S+\s+[\'"]?(?:[^\n\'"]*[;&|]\s*)?(?:{_WRITERS})\b'
        r'|(?:scp|rsync)\b[^\n;&|]*\s\S*[\w.-]:\S*\s*$)'
    ),
    'matches': 'command',
    'hazard': 'a hand-written write to a remote host leaves no record of which door, host or reason changed it.',
    'remedy': f'A server: {PYTHON_SLOT} -m dev_lab.dev.opsserver <server> <verb> [<unit>]; a cluster account: '
    f'{PYTHON_SLOT} -m '
    f'dev_lab.dev.hpcaccount {exits_of("HPC-THROUGH-THE-DOOR", "dev_lab.dev.hpcaccount")}. Read-only ssh is open.',
    'needs': None,
    'refuses': (
        'ssh ops@forge.example sudo systemctl restart gitea',
        "ssh ops@forge.example 'cd /opt/dev-lab && git pull'",
        'ssh -p 2222 root@10.0.0.5 rm -rf /srv/old',
        'ssh -J jump ops@inner "uptime; systemctl restart caddy"',
        'scp supervise.toml ops@forge.example:/etc/dev-lab/',
        'rsync -a out/ ops@forge.example:/srv/out/',
    ),
    'permits': (
        'ssh ops@forge.example uptime',
        'ssh ops@forge.example systemctl --no-pager status gitea',
        "ssh ops@forge.example 'journalctl --no-pager -u caddy -n 50'",
        'scp ops@forge.example:/var/log/x.log output/',
        'git commit -m "ssh ops@host sudo restart is refused now"',
        f'{PYTHON_SLOT} -m dev_lab.dev.opsserver forge restart gitea',
    ),
}
