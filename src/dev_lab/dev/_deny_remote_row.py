"""The agent deny registry, REMOTE-WRITE-THROUGH-A-DOOR row -- pure DATA.

User ruling 2026-11-07: a write to a remote host goes through the door named for that host's kind --
:mod:`dev_lab.dev.hpcaccount` for a cluster account, :mod:`dev_lab.dev.opsserver` for a server the integrator
deploys -- both over the one transport :mod:`dev_lab.dev.remote`. A hand-written ``ssh`` that WRITES, and an
upload by ``scp``/``rsync``, are refused here; read-only ssh (``uptime``, ``systemctl status``, ``journalctl``,
``cat``, ``ls``, ``df``) stays open. HPC login hosts are refused whole by HPC-THROUGH-THE-DOOR, which fires first.

HOW A WRITE IS RECOGNISED: by the remote command's verb, from a closed list of the shapes that change a host
(:data:`_WRITERS`), and for a copy by its LAST argument being remote (``host:path``). A list rather than an
allowlist of readers because a refusal must name its exit, and a read the list misses is merely prompted.

Two shapes are refused WHEREVER they stand in the remote command (incident 2026-11-13: ``ssh ops@host "$C"``
with ``C`` holding a ``dev_lab.ops ... --subject`` call passed this row and drew only a generic denial):

* an unexpanded ``$VAR``, ``${...}``, ``$(...)`` or backtick -- the hook cannot judge what it hides, so the
  remote command must be spelled out;
* ``dev_lab.ops`` under any verb, a ``--subject`` read included -- a host's ops entry is reached through the
  consent doors: ``planrun preflight`` asks each host for its subject through the held session,
  ``sshhold open --plan`` spends the user's one code, ``planrun run`` runs the plan.
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
    r'|docker\s+(?:run|rm|stop|start|restart|compose|pull|exec)'
)
#: Anywhere in the remote command: an expansion the hook cannot see through, or the ops entry point.
_ANYWHERE = r'\$[\w{(]|`|\bdev_lab\.ops\b'
#: ssh's options before its target: ``-o X``, ``-p 22``, ``-J jump``, ``-i key`` take a value; flags do not.
_SSH_OPTS = r'(?:\s+(?:-[oplJiFLRDwWcmbeEQS]\s*\S+|-[46AaCfGgKkMNnqsTtVvXxYy]+))*'

REMOTE_WRITE: dict[str, object] = {
    'id': _ID,
    'pattern': (
        rf'(?:ssh{_SSH_OPTS}\s+\S+\s+[\'"]?(?:[^\n\'"]*[;&|]\s*)?(?:{_WRITERS})\b'
        rf'|ssh{_SSH_OPTS}\s+\S+\s+[^\n]*(?:{_ANYWHERE})'
        r'|(?:scp|rsync)\b[^\n;&|]*\s\S*[\w.-]:\S*\s*$)'
    ),
    'matches': 'command',
    'hazard': 'a hand-written write to a remote host leaves no record of which door, host or reason changed it.',
    'remedy': 'Remote dev_lab.ops, --subject too: planrun preflight --plan P --steps S (asks each host its subject), '
    "sshhold open --hours H --plan P --digest D (the user's one code), planrun run. Else opsserver <server> <verb> "
    f'or hpcaccount {exits_of("HPC-THROUGH-THE-DOOR", "dev_lab.dev.hpcaccount")}. Spell out $VAR; read-only ssh '
    'is open.',
    'needs': None,
    'refuses': (
        'ssh ops@forge.example sudo systemctl restart gitea',
        "ssh ops@forge.example 'cd /opt/dev-lab && git pull'",
        'ssh -p 2222 root@192.0.2.5 rm -rf /srv/old',
        'ssh -J jump ops@inner "uptime; systemctl restart caddy"',
        'scp supervise.toml ops@forge.example:/etc/dev-lab/',
        'rsync -a out/ ops@forge.example:/srv/out/',
        'ssh ops@forge.example "$C"',
        'ssh ops@forge.example "${CMD}"',
        'ssh ops@forge.example "$(cat cmd.txt)"',
        'ssh ops@forge.example `cat cmd.txt`',
        'ssh ops@forge.example /opt/x/.venv/bin/python -m dev_lab.ops --config /etc/x.toml config apply --subject',
        "ssh ops@forge.example 'cd /opt/x && python3 -m dev_lab.ops consent ready'",
        'ssh -J jump ops@inner "sudo -n /opt/x/bin/python -m dev_lab.ops.consent grant r.json"',
    ),
    'permits': (
        'ssh ops@forge.example uptime',
        'ssh ops@forge.example systemctl --no-pager status gitea',
        "ssh ops@forge.example 'journalctl --no-pager -u caddy -n 50'",
        'scp ops@forge.example:/var/log/x.log output/',
        'ssh ops@forge.example df -h',
        "ssh ops@forge.example 'cat /etc/os-release'",
        'git commit -m "ssh ops@host sudo restart is refused now"',
        f'{PYTHON_SLOT} -m dev_lab.dev.opsserver forge restart gitea',
    ),
}
