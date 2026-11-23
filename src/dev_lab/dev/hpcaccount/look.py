"""``python -m dev_lab.dev.hpcaccount look --account <user> <what> [<repo>]`` -- a READ-ONLY look at one account.

Measured 2026-11-23: a key-only verification account's tick was hung and nothing could see it -- raw ssh is
forbidden, ``sshhold`` is for a key+TOTP host only (it asked a code there and died), and no ``hpcaccount`` verb read
a process or a log. This door reads, through the grant's own runner (:func:`~dev_lab.dev.hpcaccount.transport.
grant_runner`: the rate-limited, shared key ssh of :mod:`lab_commons.hpc.sshgate`), pinned to the account's declared
login host (where its crontab and its ticks live), ONE of a CLOSED set of reads (:data:`READS`):

* ``processes`` -- this user's processes there: pid, parent, elapsed seconds, command line;
* ``ticks`` -- every tick lock under ``<root>/serve`` and its holder record (pid, start, phase;
  :mod:`dev_lab.dev.tickholder`);
* ``log <repo>`` -- the last :data:`LOG_LINES` lines of that repo's tick/cron log, ``<root>/serve/<repo>.log``;
* ``crontab`` -- ``crontab -l``;
* ``stuck <path>`` -- why entries under ``~/<path>`` cannot be removed (measured 2026-11-23: 206,412 entries kept
  with "Operation not permitted" and no read could say why): ``id``, the filesystem type, ``ls -ld`` and
  ``lsattr -d`` of every ancestor (GPFS keeps no such flags: ``lsattr`` says so), the owners and modes counted,
  the directories lacking ``u+wx``, and ``stat``/``lsattr``/``getfacl`` of one sample file.

There is no free-form command: each read is a fixed shell line whose only inputs are the declared root, a repo
name of :data:`REPO_NAME`'s shape and a home-relative path of such names
(``stuck``), so the door cannot write. Anything else is refused naming the set. A verification
account needs this session's integrator role, as every verb (:func:`~dev_lab.dev.hpcaccount.division.reached_machine`).
"""

from __future__ import annotations

import argparse
import functools
import re
import shlex
import subprocess
from collections.abc import Callable, Sequence
from typing import Final

from lab_commons.hpc.cluster import Runner, Unreachable
from lab_commons.log import emit

from dev_lab.dev.hpcaccount.division import reached_machine
from dev_lab.dev.hpcaccount.fleet import declared_target
from dev_lab.dev.hpcaccount.storage import UNREACHABLE, Pin, on_host
from dev_lab.dev.hpcaccount.transport import grant_runner

__all__ = ['LOG_LINES', 'READS', 'REPO_NAME', 'command_of', 'look', 'main']

#: How many lines of a tick log ``log`` reads.
LOG_LINES: Final = 200
#: A repo name a read may carry: a checkout name, never a path or a shell word.
REPO_NAME: Final = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')
#: The closed set of reads, each with what it shows.
READS: Final = {
    'processes': "this user's processes on the declared login host",
    'ticks': 'every tick lock under <root>/serve and who holds it',
    'log': "the tail of one repo's tick/cron log (log <repo>)",
    'crontab': 'crontab -l',
    'stuck': 'why entries under ~/<path> cannot be removed (stuck <path>)',
}
#: The reads that take an argument: ``log`` a repo name, ``stuck`` a home-relative path of such names.
_TAKES = {'log': 'repo', 'stuck': 'path'}
_TIMEOUT_S: Final = 120.0


def command_of(what: str, repo: str, root: str) -> str:
    """The fixed shell line of read *what* (*repo* for ``log``) under *root*.

    Raises:
        ValueError: not one of :data:`READS`, or a repo that is not a checkout name -- named, nothing run.

    """
    if what not in READS:
        msg = f'look: {what!r} is not a read -- the reads are {", ".join(READS)}; there is no free-form command'
        raise ValueError(msg)
    if (what in _TAKES) != bool(repo):
        msg = 'look: log takes exactly one repo, stuck one home-relative path; no other read takes one'
        raise ValueError(msg)
    if repo and not all(REPO_NAME.fullmatch(part) and part != '..' for part in repo.split('/')):
        msg = f'look: {repo!r} is not a {_TAKES[what]} of names ({REPO_NAME.pattern}, joined by /, no ..)'
        raise ValueError(msg)
    serve = shlex.quote(f'{root}/serve')
    return {
        'processes': 'ps -u "$(id -un)" -o pid=,ppid=,etimes=,args= | cut -c1-300',
        'ticks': (
            f'cd {serve} 2>/dev/null || {{ echo "no serve dir at {root}/serve"; exit 0; }}; '
            'for f in *.lock; do [ -e "$f" ] || continue; echo "== $f"; '
            'if [ -s "$f.holder" ]; then cat "$f.holder"; echo; else echo "(no holder record)"; fi; done'
        ),
        'log': f'tail -n {LOG_LINES} {shlex.quote(f"{root}/serve/{repo}.log")}',
        'crontab': 'crontab -l 2>&1',
        'stuck': (
            f'p="$HOME"/{shlex.quote(repo)}; echo "== id"; id; echo "== fs"; stat -f -c "%T" "$p" 2>&1; '
            'echo "== ancestors"; d="$p"; while [ "$d" != / ]; do ls -ld "$d" 2>&1; lsattr -d "$d" 2>&1; '
            'd=$(dirname "$d"); done; '
            'echo "== owners"; find "$p" -printf "%u:%g\\n" 2>/dev/null | sort | uniq -c | sort -rn | head; '
            'echo "== modes"; find "$p" -printf "%y %M\\n" 2>/dev/null | sort | uniq -c | sort -rn | head; '
            'echo "== dirs lacking u+wx"; find "$p" -type d ! -perm -u+w -o -type d ! -perm -u+x 2>/dev/null '
            '| head -5; '
            'echo "== sample"; f=$(find "$p" ! -type d 2>/dev/null | head -1); stat -c "%U %a %n" "$f" 2>&1; '
            'lsattr "$f" 2>&1; getfacl -p "$f" 2>&1 | head -12'
        ),
    }[what]


def look(
    user: str,
    what: str,
    repo: str = '',
    *,
    connect: Callable[..., Runner] = grant_runner,
    pin: Pin = on_host,
    say: Callable[[str], None] = emit,
) -> int:
    """Run read *what* on *user*'s account and say what it printed; 2 refused or unreachable."""
    try:
        command_of(what, repo, '/')  # the request is judged before anything is reached
        grant = next(g for g in reached_machine([user]).grants if g.user == user)
        target = declared_target(grant, connect(grant))
        if isinstance(target, str):
            say(target)
            return 2
        out = pin(grant, target.host)(command_of(what, repo, target.root), None)
    except subprocess.TimeoutExpired as slow:
        say(f'look: {user}: refused -- the read ran past {slow.timeout:.0f} s')
        return 2
    except Unreachable:
        say(f'look: {user}: refused -- {UNREACHABLE}')
        return 2
    except (ValueError, PermissionError, LookupError, RuntimeError, OSError) as refused:
        say(str(refused) if str(refused).startswith('look:') else f'look: {user}: refused -- {refused}')
        return 2
    say(f'{user}@{target.host}: {what}{f" {repo}" if repo else ""}')
    for line in out.rstrip().splitlines():
        say(line)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``look`` and run it."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount look', description=__doc__.splitlines()[0])
    parser.add_argument('--account', required=True, help='one account of the fleet')
    parser.add_argument('what', help=f'one of: {", ".join(READS)}')
    parser.add_argument('repo', nargs='?', default='', help='the repo of `log`, the home-relative path of `stuck`')
    args = parser.parse_args(list(argv or ()))
    return look(args.account, args.what, args.repo, connect=functools.partial(grant_runner, timeout=_TIMEOUT_S))
