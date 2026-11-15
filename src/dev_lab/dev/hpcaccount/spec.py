"""The cluster deployment's DATA: the ``[deploy]`` declaration, and the crontab lines derived from it.

AN ACCOUNT HAS A ROLE (user ruling 2026-11-06), declared ONCE as ``[deploy] role`` in its own machine file -- the
table its deploy, its tick, its host card and the workstation's ``deploy-fleet`` all read: ``"verification"`` (a
Forge Verification account: it runs the forge serve cron) or ``"research"`` (checkouts and venvs for research,
never a serve cron). Undeclared, nothing is ticked and the deploy refuses (:func:`role_refusal`). What a role
DOES is the workstation's data (:mod:`dev_lab.dev.hpcaccount.division`, user ruling 2026-11-09), passed by
``deploy-fleet``; a hand-run deploy falls back to its shipped defaults.

Pure: parse, render, derive. :mod:`dev_lab.dev.hpcaccount.deploy` runs the steps.
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
import tomllib
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

from lab_commons.hpc.grants import declared_grants
from lab_commons.hpc.retired import RETIRED

from dev_lab.dev._machinefile import dumps
from dev_lab.dev.hpcaccount.division import DEFAULT_ROLES

__all__ = [
    'DEFAULT_PYTHON',
    'DEFAULT_ROOT',
    'DEFAULT_TICK_MINUTES',
    'KIT',
    'MARK',
    'RESEARCH',
    'VERIFICATION',
    'Deployment',
    'Repo',
    'checkout_of',
    'cron_lines',
    'has_grant',
    'host_serve_argv',
    'load',
    'merge_crontab',
    'parse_repo',
    'render',
    'render_grant',
    'role_refusal',
    'tick_command',
    'tick_dirs',
    'tick_environment',
    'ticked',
    'uv_cache',
]

#: Every crontab line this tool owns ends with this comment plus the repo's name.
MARK: Final = '# lab-commons-deploy:'

#: Where the served checkouts live, under the account's home: the forge home's ``repos`` (the workstation's
#: :func:`dev_lab.dev.servelock` home on Linux), never ``~/src`` -- a home ``src`` is a write-prone root nothing
#: scans (WRITES-STAY-IN-THE-TREE), and ~/src was retired (user rulings 2026-10-26, 2026-11-06).
DEFAULT_ROOT: Final = '.local/share/lab-forge/repos'
DEFAULT_PYTHON: Final = '3.13'

#: ``[schedule] tick_minutes`` when undeclared -- the same default the host card is judged stale against.
DEFAULT_TICK_MINUTES: Final = 5

#: The served repo every tick RUNS -- the kit, whose ``forge serve`` serves every other served repo.
KIT: Final = 'dev-lab'

#: The two shipped role names (their semantics: :data:`dev_lab.dev.hpcaccount.division.DEFAULT_ROLES`).
VERIFICATION: Final = 'verification'
RESEARCH: Final = 'research'
_ROLE_NAME: Final = re.compile(r'[a-z][a-z0-9-]*')

#: The interpreter a cron line runs: the line is a Linux login node's, so the POSIX venv layout is the only one.
_VENV_PYTHON: Final = str(PurePosixPath('.venv', 'bin', 'python'))


@dataclass(frozen=True)
class Repo:
    """One declared repository: checkout name, HTTPS remote, followed branch, and whether its queue is served.

    ``serve = false`` checks it out and installs it without serving its queue: on the kit (dev-lab) its own
    tick still refreshes the kit (the one writer of that checkout) and serves nothing; any other such repo
    gets no crontab line. ``verify`` names the status contexts of this repo the account is the DEFAULT producer
    of (HPC account affinity, :mod:`dev_lab.dev.forgeaffinity`): ``verify = ["tests/*"]`` on a verify account's row.
    """

    name: str
    url: str
    ref: str
    serve: bool = True
    verify: tuple[str, ...] = ()


@dataclass(frozen=True)
class Deployment:
    """The ``[deploy]`` table of the machine file, plus the ``[schedule] tick_minutes`` its cron lines run at.

    ``slurm_account`` and ``partitions`` declare this account's grant; ``role`` names its role, ``''`` when
    undeclared (nothing is ticked, the deploy refuses).
    """

    host: str
    root: str
    python: str
    repos: tuple[Repo, ...]
    slurm_account: str = ''  # needed only when sacctmgr names several
    partitions: tuple[str, ...] = ()
    role: str = ''
    tick_minutes: int = DEFAULT_TICK_MINUTES  # from [schedule], never [deploy]: one period per host


def load(path: Path) -> Deployment | None:
    """The ``[deploy]`` table of the machine file at *path*; ``None`` when undeclared, a missing key refused."""
    table = tomllib.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    raw = table.get('deploy')
    if not raw:
        return None
    if retired := [
        f'[deploy] {key} is retired: {RETIRED[f"[deploy] {key}"]}' for key in raw if f'[deploy] {key}' in RETIRED
    ]:
        msg = f'{path}: ' + '; '.join(retired)
        raise ValueError(msg)
    try:
        return Deployment(
            host=raw['host'],
            root=raw.get('root', DEFAULT_ROOT),
            python=raw.get('python', DEFAULT_PYTHON),
            repos=tuple(
                Repo(r['name'], r['url'], r['ref'], r.get('serve', True), tuple(r.get('verify', ())))
                for r in raw['repos']
            ),
            slurm_account=raw.get('slurm_account', ''),
            partitions=tuple(raw.get('partitions', ())),
            role=_role(path, raw.get('role', '')),
            tick_minutes=_tick_minutes(path, table.get('schedule', {})),
        )
    except KeyError as missing:
        msg = f'[deploy] in {path} lacks {missing}'
        raise ValueError(msg) from None


def _role(path: Path, role: object) -> str:
    """``[deploy] role``: a role name, or ``''`` when undeclared; anything else refused naming the key."""
    if role != '' and not (isinstance(role, str) and _ROLE_NAME.fullmatch(role)):
        msg = f'[deploy] role in {path} is {role!r}: declare a role name such as {VERIFICATION!r} or {RESEARCH!r}'
        raise ValueError(msg)
    return str(role)


def role_refusal(spec: Deployment, path: Path) -> str:
    """``''`` when *spec* declares its role; else why the deploy refuses -- a deploy never serves silently."""
    if spec.role:
        return ''
    return (
        f'[deploy] role is undeclared in {path}: declare role = "{VERIFICATION}" (a Forge Verification account, '
        f'which runs the forge serve cron) or role = "{RESEARCH}" (never serves) -- user ruling 2026-11-06'
    )


def _tick_minutes(path: Path, schedule: Mapping[str, Any]) -> int:
    """``[schedule] tick_minutes`` as a cron step: a whole number of minutes dividing the hour, else refused."""
    minutes = schedule.get('tick_minutes', DEFAULT_TICK_MINUTES)
    if type(minutes) is not int or minutes < 1 or 60 % minutes:
        msg = f'[schedule] tick_minutes in {path} is {minutes!r}: cron needs a whole number of minutes dividing 60'
        raise ValueError(msg)
    return minutes


def _unserved(repo: Repo) -> str:
    return ('' if repo.serve else ', serve = false') + (f', verify = {_list(repo.verify)}' if repo.verify else '')


def _toml(value: str) -> str:
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def render(spec: Deployment) -> str:
    """*spec* as the ``[deploy]`` TOML table :func:`load` reads back."""
    repos = ''.join(
        f'  {{ name = {_toml(r.name)}, url = {_toml(r.url)}, ref = {_toml(r.ref)}{_unserved(r)} }},\n'
        for r in spec.repos
    )
    account = f'slurm_account = {_toml(spec.slurm_account)}\n' if spec.slurm_account else ''
    account += f'role = {_toml(spec.role)}\n' if spec.role else ''
    return (
        f'\n[deploy]\nhost = {_toml(spec.host)}\nroot = {_toml(spec.root)}\npython = {_toml(spec.python)}\n'
        f'{account}partitions = {_list(spec.partitions)}\nrepos = [\n{repos}]\n'
    )


def _list(values: Sequence[str]) -> str:
    return '[' + ', '.join(_toml(v) for v in values) + ']'


def render_grant(table: Mapping[str, Any]) -> str:
    """*table* (an ``[hpc]`` slice) as the machine-file text :mod:`lab_commons.hpc.grants` reads."""
    return '\n' + dumps({'hpc': dict(table)})


def _hpc_of(path: Path) -> dict[str, Any]:
    return (tomllib.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}).get('hpc', {})


def has_grant(path: Path, user: str) -> bool:
    """Whether the machine file at *path* already grants *user*."""
    return any(grant.get('user') == user for grant in _hpc_of(path).get('grant', []))


def grant_refusal(path: Path) -> str:
    """Why this kit cannot load the ``[hpc]`` slice of the machine file at *path* (``''``: it loads)."""
    try:
        declared_grants(_hpc_of(path))
    except ValueError as refused:
        return str(refused)
    return ''


#: A TOML table or array-of-tables header line; group 1 is the table's dotted name.
_HEADER: Final = re.compile(r'^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$')


def without_hpc(text: str) -> str:
    """*text* without its ``[hpc]`` slice -- every ``[hpc]``, ``[hpc.*]`` and ``[[hpc.*]]`` table; the rest kept."""
    kept: list[str] = []
    inside = False
    for line in text.splitlines():
        if header := _HEADER.match(line):
            name = header.group(1)
            inside = name == 'hpc' or name.startswith('hpc.')
        if not inside:
            kept.append(line)
    return '\n'.join(kept).rstrip('\n') + '\n'


def grant_setup(path: Path, user: str) -> tuple[str, ...]:
    """The set-up of *user*'s cluster, as the machine file at *path* declares it -- the cluster's own environment."""
    hpc = _hpc_of(path)
    if not any(grant.get('user') == user for grant in hpc.get('grant', [])):
        return ()
    grants, _ = declared_grants(hpc)
    return next((grant.setup for grant in grants if grant.user == user), ())


def parse_repo(text: str) -> Repo:
    """A ``--repo <name>=<https url>@<branch>`` argument."""
    name, _, rest = text.partition('=')
    url, _, ref = rest.rpartition('@')
    if not (name and url.startswith('https://') and ref):
        msg = f'--repo {text!r}: expected <name>=<https url>@<branch>'
        raise argparse.ArgumentTypeError(msg)
    return Repo(name, url, ref)


def cron_lines(
    spec: Deployment,
    home: Path,
    *,
    serves: bool | None = None,
    slurm: Sequence[str] = (),
    setup: Sequence[str] = (),
) -> list[str]:
    """One marked line per served repo and the kit, every ``tick_minutes``, under ``flock -n``.

    The minute offset is derived from *home* (one per account), so accounts sharing a forge tick staggered
    rather than in lockstep; an unserved repo other than the kit gets no line (:class:`Repo`).
    """
    step = spec.tick_minutes
    minute = f'{zlib.crc32(str(home).encode()) % step}-59/{step}'
    return [
        f'{minute} * * * * {tick_command(spec, home, repo, log=True, slurm=slurm, setup=setup)} {MARK}{repo.name}'
        for repo in ticked(spec, serves=serves)
    ]


def ticked(spec: Deployment, *, serves: bool | None = None) -> tuple[Repo, ...]:
    """The repos this account TICKS: every served one, and the kit (whose own tick refreshes its checkout).

    Only an account whose role SERVES ticks -- *serves* as the workstation's role table says, else the shipped
    default for its role (:data:`dev_lab.dev.hpcaccount.division.DEFAULT_ROLES`); undeclared ticks nothing.
    """
    if not (DEFAULT_ROLES.get(spec.role, {}).get('serves', False) if serves is None else serves):
        return ()
    return tuple(repo for repo in spec.repos if repo.serve or repo.name == KIT)


def merge_crontab(current: str, lines: Sequence[str]) -> str:
    """*current* without any line this tool marked, plus *lines*; every other line kept in place."""
    kept = [line for line in current.splitlines() if MARK not in line]
    text = '\n'.join([*kept, *lines])
    return text + '\n' if text else ''


def tick_command(
    spec: Deployment, home: Path, repo: Repo, *, log: bool, slurm: Sequence[str] = (), setup: Sequence[str] = ()
) -> str:
    """The shell command of one tick of *repo*: :func:`tick_environment`, ``flock -n``, the HOST's ``hpc tick``.

    It runs from the kit (dev-lab) checkout's venv, never the repo's: the host refreshes the repo (and
    itself), then serves it with its own kit (:func:`host_serve_argv`), so a stale repo venv blocks nothing.
    With a grant *setup* the whole tick runs in ONE ``bash -lc`` (``module`` is a login-shell function), so
    every tool it loads runs inside the environment that loaded it -- a module's binary does not run outside
    it (Ada 2026-10-17: git 2.42 alone wants ``libiconv.so.2``).
    """
    cache = home / '.cache'
    lab = next(one for one in spec.repos if one.name == KIT)
    command = (
        f'{tick_environment(home, slurm, setup)}; cd {shlex.quote(str(checkout_of(spec, home, lab)))} && '
        f'flock -n {shlex.quote(str(cache / f"lab-forge-{repo.name}.lock"))} '
        f'{_VENV_PYTHON} -m dev_lab.dev.hpcaccount tick {shlex.quote(repo.name)}'
    )
    command = f'bash -lc {shlex.quote(command)}' if setup else command
    return command + (f' >> {shlex.quote(str(cache / f"lab-forge-{repo.name}.log"))} 2>&1' if log else '')


def tick_environment(home: Path, slurm: Sequence[str] = (), setup: Sequence[str] = ()) -> str:
    """The shell prefix that makes a tick's environment: cron's PATH (:func:`tick_dirs`), then the grant *setup*.

    The ONE definition of that environment: the cron line runs it, and the deploy proves the tick's git in it.
    """
    cache = shlex.quote(str(uv_cache(home)))
    exported = f'export UV_CACHE_DIR={cache} UV_LINK_MODE=hardlink'
    return '; '.join([f'PATH={":".join(tick_dirs(home, slurm))}', exported, *setup])


def uv_cache(home: Path) -> Path:
    """The account's ONE uv cache: every uv the kit runs there shares it, and every env hardlinks from it.

    It lives under the forge's ``ci`` root, on the same filesystem as the envs it links into, so a hardlink
    never falls back to a copy. uv's own default (``~/.cache/uv``) is retired: a second cache doubled an
    account's files (census 2026-11-14), and retention removes it (:func:`dev_lab.dev.retentionplan`).
    """
    return home / 'ci' / 'uv-cache'


def tick_dirs(home: Path, slurm: Sequence[str] = ()) -> list[str]:
    """The directories of a tick's PATH, in order: cron's own PATH is not the login shell's.

    *slurm* is where ``sbatch``, ``sacct`` and ``squeue`` resolved when the deploy ran -- a site install
    (``/opt/slurm/<version>/bin``) that cron's PATH never names. A tool the grant's ``setup`` loads is never
    named here: it runs inside that setup (:func:`tick_environment`).
    """
    base = [str(home / '.local/bin'), str(home / '.cargo/bin'), '/usr/local/bin', '/usr/bin', '/bin']
    return [*base, *(d for d in dict.fromkeys(slurm) if d not in base)]


def checkout_of(spec: Deployment, home: Path, repo: Repo) -> Path:
    """Where *repo* is checked out: ``<root>/<name>``, a relative *root* under *home*.

    An absolute root is taken as is: a site whose compute nodes never see home (``/work/...``).
    """
    root = PurePosixPath(spec.root)
    return (Path(root) if root.is_absolute() else home / root) / repo.name


def host_serve_argv() -> list[str]:
    """``forge serve`` as THE HOST KIT runs it, in a served repo's checkout (cwd): the one scheduler on a host.

    The interpreter is this process's -- the host's dev-lab -- never the repo's venv: a repo venv holds
    whatever kit it pinned (a non-editable older one, measured), so serving from it ran a second scheduler
    the host's fixes never reached. The repo's venv only runs its producers, in their trees. ``-P`` keeps
    the checkout (the cwd) off ``sys.path``, so the repo's files never shadow the kit.
    """
    python = Path(sys.executable)  # under the Task's windowless interpreter, its console twin keeps the streams
    console = python.with_name(python.name.lower().replace('pythonw', 'python'))
    return [str(console if console.is_file() else python), '-P', '-m', 'dev_lab.dev.forge', 'serve']
