"""``python -m dev_lab.dev.hpcaccount look --account <user> <what> [<repo>]`` -- a READ-ONLY look at one account.

Measured 2026-11-23: a key-only verification account's tick was hung and nothing could see it -- raw ssh is
forbidden, ``sshhold`` is for a key+TOTP host only (it asked a code there and died), and no ``hpcaccount`` verb read
a process or a log. This door reads, through the grant's own runner (:func:`~dev_lab.dev.hpcaccount.transport.
grant_runner`: the rate-limited, shared key ssh of :mod:`lab_commons.hpc.sshgate`), pinned to the account's declared
login host (where its crontab and its ticks live), ONE of a CLOSED set of reads (:data:`READS`):

* ``processes`` -- this user's processes there: pid, parent, elapsed seconds, command line;
* ``ticks`` -- every tick lock under ``<root>/serve`` and its holder record (pid, start, phase;
  :mod:`dev_lab.dev.tickholder`);
* ``log`` -- the last :data:`LOG_LINES` lines of the account's ONE tick/cron log, ``<root>/serve/tick.log``
  (:data:`~dev_lab.dev.hpcaccount.spec.TICK_LOG`: one poller per account, ONE-LOGIN-POLLER);
* ``crontab`` -- ``crontab -l``, refused (exit 2) when it holds more than the account's one poller, naming each line
  (ONE-LOGIN-POLLER, :func:`~dev_lab.dev.hpcaccount.cronline.crontab_refusal`);
* ``stuck <path>`` -- why entries under ``~/<path>`` cannot be removed (measured 2026-11-23: 206,412 entries kept
  with "Operation not permitted" and no read could say why): ``id``, the filesystem type, ``ls -ld`` and
  ``lsattr -d`` of every ancestor (GPFS keeps no such flags: ``lsattr`` says so), the owners and modes counted,
  the directories lacking ``u+wx``, and ``stat``/``lsattr``/``getfacl`` of one sample file;
* ``inventory <path>`` -- what ``~/<path>`` holds before it is archived or cleaned: each entry's files, bytes and
  newest change, and every git checkout in it judged pushed or NOT PUSHED (:mod:`~dev_lab.dev.hpcaccount.inventory`,
  whose rows are printed instead of the raw lines);
* ``modules [<pattern>]`` -- the Lmod modules matching *pattern* (``module -t avail``, ``module -t spider`` when
  avail lists none), one ``name/version`` per line (:func:`module_rows`);
* ``where <module> <tool>`` -- after ``module load <module>`` in the read's own shell (nothing persists): the
  modules loaded, the tool's resolved path and its real path. Measured 2026-11-28: the AEDT install had to be
  compared across every account and no read could say which module or path an account resolves.

There is no free-form command: each read is a fixed shell line whose only inputs are the declared root, a repo
name of :data:`REPO_NAME`'s shape and a home-relative path of such names
(``stuck``, ``inventory``), so the door cannot write. Anything else is refused naming the set. A verification
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

from lab_commons.hpc.cluster import Runner
from lab_commons.log import emit

from dev_lab.dev.hpcaccount import inventory
from dev_lab.dev.hpcaccount.cronline import crontab_refusal
from dev_lab.dev.hpcaccount.division import reached_machine
from dev_lab.dev.hpcaccount.fleet import declared_target
from dev_lab.dev.hpcaccount.spec import TICK_LOG
from dev_lab.dev.hpcaccount.storage import Pin, on_host
from dev_lab.dev.hpcaccount.transport import grant_runner

__all__ = [
    'LOG_LINES',
    'MODULE_NAME',
    'READS',
    'REPO_NAME',
    'STALE_KIT_DOOR',
    'command_of',
    'home_path',
    'look',
    'main',
    'module_rows',
    'modules_command',
    'where_command',
]

#: How many lines of a tick log ``log`` reads.
LOG_LINES: Final = 200
#: A repo name a read may carry: a checkout name, never a path or a shell word.
REPO_NAME: Final = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')
#: A module name or pattern (``ansys``, ``ansys/2024R1``, ``AEDT``): never a shell word, never ``..``.
MODULE_NAME: Final = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+/-]*')
#: What ``module`` needs in a non-login shell: the system profile, its chatter discarded.
_LMOD: Final = '. /etc/profile >/dev/null 2>&1; '
#: The door when the kit's lab-commons predates the machine file's schema (a key it does not know).
STALE_KIT_DOOR: Final = (
    "the kit's lab-commons is older than the machine file -- sync it: "
    'python -m dev_lab.dev.dep --sync in the kit (or python -m dev_lab.dev.dep --bootstrap <worktree>)'
)
#: The closed set of reads, each with what it shows.
READS: Final = {
    'processes': "this user's processes on the declared login host",
    'ticks': 'every tick lock under <root>/serve and who holds it',
    'log': "the tail of the account's one tick/cron log",
    'crontab': 'crontab -l',
    'stuck': 'why entries under ~/<path> cannot be removed (stuck <path>)',
    'inventory': 'what ~/<path> holds: entries, and each git checkout pushed or not (inventory <path>)',
    'modules': 'the Lmod modules matching a pattern (modules [<pattern>])',
    'where': 'the path a tool resolves to after module load (where <module> <tool>)',
}
#: The reads that take an argument: ``stuck`` and ``inventory`` a home-relative path of such names.
_TAKES = {'stuck': 'path', 'inventory': 'path'}
_TIMEOUT_S: Final = 120.0


def home_path(path: str, what: str = 'path') -> str:
    """*path* when it is a home-relative path of :data:`REPO_NAME` names joined by ``/`` (never ``..``, never absolute).

    Raises:
        ValueError: anything else -- named, nothing run.

    """
    if not path or not all(REPO_NAME.fullmatch(part) and part != '..' for part in path.split('/')):
        msg = f'look: {path!r} is not a {what} of names ({REPO_NAME.pattern}, joined by /, no ..)'
        raise ValueError(msg)
    return path


def _module(name: str, what: str) -> str:
    if not MODULE_NAME.fullmatch(name) or '..' in name:
        msg = f'look: {name!r} is not a {what} ({MODULE_NAME.pattern}, no ..)'
        raise ValueError(msg)
    return name


def modules_command(pattern: str = '') -> str:
    """``module -t avail <pattern>``, then ``module -t spider <pattern>`` when avail lists none.

    Raises:
        ValueError: a pattern that is not a module name -- named, nothing run.

    """
    arg = f' {_module(pattern, "module pattern")}' if pattern else ''
    return (
        f'{_LMOD}out=$(module -t avail{arg} 2>&1); '
        'if printf "%s\\n" "$out" | grep -qv -e ":$" -e "^$"; then printf "%s\\n" "$out"; '
        f'else module -t spider{arg} 2>&1; fi'
    )


def where_command(module: str, tool: str) -> str:
    """``module load <module>`` in this read's own shell, then the loaded list and *tool*'s path and real path.

    Raises:
        ValueError: a missing or malformed module or tool -- named, nothing run.

    """
    if not module or not tool or not REPO_NAME.fullmatch(tool):
        msg = 'look: where takes <module> <tool>: a module name and a command name'
        raise ValueError(msg)
    _module(module, 'module name')
    return (
        f'{_LMOD}module load {module} 2>&1; echo "== loaded"; module -t list 2>&1; '
        f'echo "== path"; p=$(command -v {tool}) && {{ echo "$p"; echo "== realpath"; readlink -f "$p"; }} '
        f'|| echo "{tool}: not on PATH after module load {module}"'
    )


def module_rows(out: str) -> list[str]:
    """The ``name/version`` lines of a ``module -t`` listing: directory headers (``...:``) and blanks dropped."""
    return [line.strip() for line in out.splitlines() if line.strip() and not line.rstrip().endswith(':')]


def command_of(what: str, repo: str, root: str) -> str:
    """The fixed shell line of read *what* (*repo*: the path of ``stuck`` and ``inventory``) under *root*.

    Raises:
        ValueError: not one of :data:`READS`, or a repo that is not a checkout name -- named, nothing run.

    """
    if what not in READS:
        msg = f'look: {what!r} is not a read -- the reads are {", ".join(READS)}; there is no free-form command'
        raise ValueError(msg)
    if what == 'modules':
        return modules_command(repo)
    if what == 'where':
        module, _, tool = repo.partition(' ')
        return where_command(module, tool)
    if (what in _TAKES) != bool(repo):
        msg = 'look: stuck and inventory take one home-relative path; no other read takes one'
        raise ValueError(msg)
    if repo:
        home_path(repo, _TAKES[what])
    if what == 'inventory':
        return inventory.command(repo)
    serve = shlex.quote(f'{root}/serve')
    return {
        'processes': 'ps -u "$(id -un)" -o pid=,ppid=,etimes=,args= | cut -c1-300',
        'ticks': (
            f'cd {serve} 2>/dev/null || {{ echo "no serve dir at {root}/serve"; exit 0; }}; '
            'for f in *.lock; do [ -e "$f" ] || continue; echo "== $f"; '
            'if [ -s "$f.holder" ]; then cat "$f.holder"; echo; else echo "(no holder record)"; fi; done'
        ),
        'log': f'tail -n {LOG_LINES} {shlex.quote(f"{root}/serve/{TICK_LOG}")}',
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
    except (ValueError, PermissionError, LookupError, RuntimeError, OSError) as refused:
        door = f' -- {STALE_KIT_DOOR}' if 'has unknown keys' in str(refused) else ''
        say(str(refused) if str(refused).startswith('look:') else f'look: {user}: refused -- {refused}{door}')
        return 2
    say(f'{user}@{target.host}: {what}{f" {repo}" if repo else ""}')
    rows = {'inventory': inventory.rows, 'modules': module_rows}.get(what, lambda o: o.rstrip().splitlines())
    for line in rows(out):
        say(line)
    if what == 'crontab' and (why := crontab_refusal(out)):
        say(f'look: {user}: refused -- {why}')
        return 2
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``look`` and run it."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount look', description=__doc__.splitlines()[0])
    parser.add_argument('--account', required=True, help='one account of the fleet')
    parser.add_argument('what', help=f'one of: {", ".join(READS)}')
    parser.add_argument(
        'repo', nargs='*', help='the path of stuck/inventory, the pattern of modules, <module> <tool> of where'
    )
    args = parser.parse_args(list(argv or ()))
    return look(
        args.account, args.what, ' '.join(args.repo), connect=functools.partial(grant_runner, timeout=_TIMEOUT_S)
    )
