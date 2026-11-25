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
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from lab_commons import quantity
from lab_commons.hpc.layout import ROOT_VAR, AccountPaths, RootUndeclared, account_paths
from lab_commons.hpc.retired import RETIRED
from lab_commons.quantity import Renamed, refuse_renamed

from dev_lab.dev.hpcaccount.division import DEFAULT_ROLES
from dev_lab.dev.hpcaccount.grantslice import granted_root, machine_table
from dev_lab.dev.roles import HPC, ROLES, Roles, Unbound, roles_at, roles_of_url
from dev_lab.dev.venvpointer import shell_interpreter

__all__ = [
    'CLAIMS',
    'DEFAULT_PYTHON',
    'DEFAULT_TICK',
    'DEFAULT_TICK_WALL',
    'KIT',
    'MARK',
    'RESEARCH',
    'VERIFICATION',
    'Deployment',
    'Repo',
    'checkout_of',
    'cron_lines',
    'host_serve_argv',
    'load',
    'merge_crontab',
    'parse',
    'parse_repo',
    'paths_of',
    'render',
    'role_refusal',
    'schedule_tick',
    'served',
    'serves_here',
    'tick_command',
    'tick_dirs',
    'tick_environment',
    'ticked',
    'unserved',
    'uv_cache',
]

#: Every crontab line this tool owns ends with this comment plus the repo's name.
MARK: Final = '# lab-commons-deploy:'

DEFAULT_PYTHON: Final = '3.13'

#: ``[schedule] tick`` when undeclared, in seconds -- the same default the host card is judged stale against.
DEFAULT_TICK: Final = 5 * 60

#: ``[schedule] tick_wall`` when undeclared, in seconds: how long one tick may hold its lock before it ends itself
#: (:mod:`dev_lab.dev.hpcaccount.tickwall`). WHY 40: a verification account ticks every 15 minutes and its card reads
#: STALE after three periods (:data:`dev_lab.dev.forgehosts.STALE_TICKS`), 45 minutes -- a tick ending by 40 lets the
#: next one publish before the queue calls the host down, and 40 minutes still holds a whole gather and post of a
#: large run (a submit's hour-long collection runs detached, :func:`dev_lab.dev.forgesubmit.detach`). Measured
#: 2026-11-23: unbounded, one tick in a gather's tenth retry round held the lock for hours.
DEFAULT_TICK_WALL: Final = 40 * 60

#: ``[schedule]`` keys retired by the 2026-11-25 ruling (the value carries its unit), refused with their new line.
SCHEDULE_RENAMED: Final = {'tick_minutes': Renamed('tick', 'min'), 'tick_wall_minutes': Renamed('tick_wall', 'min')}

#: The served repo every tick RUNS -- the kit, whose ``forge serve`` serves every other served repo.
KIT: Final = 'dev-lab'

#: The two shipped role names (their semantics: :data:`dev_lab.dev.hpcaccount.division.DEFAULT_ROLES`).
VERIFICATION: Final = 'verification'
RESEARCH: Final = 'research'
_ROLE_NAME: Final = re.compile(r'[a-z][a-z0-9-]*')


#: What a ``[deploy] repos`` row may narrow its claims to; undeclared claims everything.
CLAIMS: Final = ('integration', 'none')


@dataclass(frozen=True)
class Repo:
    """One declared repository: checkout name, HTTPS remote, followed branch.

    Whether its queue is served here is NOT declared here: it is the family's roles binding
    (:func:`serves_here`, D73) -- a repo with no role bound to this grant role is checked out, installed and never
    served; the kit's own tick still refreshes the kit (the one writer of that checkout). ``verify`` names
    the status contexts of this repo the account is the DEFAULT producer of (HPC account affinity,
    :mod:`dev_lab.dev.forgeaffinity`): ``verify = ["tests/*"]`` on a verify account's row. ``claims`` narrows what
    this account claims of the repo's queue while the integrator widens it step by step (user ruling 2026-11-20: a
    returning verification account first verifies each repo's integration tip, one repo at a time): ``"none"``
    claims nothing, ``"integration"`` only the integration branch's tip; undeclared claims everything.
    """

    name: str
    url: str
    ref: str
    verify: tuple[str, ...] = ()
    claims: str = ''


@dataclass(frozen=True)
class Deployment:
    """The ``[deploy]`` table of the machine file, plus the ``[schedule] tick`` its cron lines run at.

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
    tick: int = DEFAULT_TICK  # seconds, from [schedule], never [deploy]: one period per host
    tick_wall: int = DEFAULT_TICK_WALL  # seconds, from [schedule]: how long one tick may hold its lock
    env: tuple[tuple[str, str], ...] = ()  # from [env]: this account's own tool paths, exported in every tick


def load(path: Path, *, root: str = '') -> Deployment | None:
    """The ``[deploy]`` table of the machine file at *path*; ``None`` when undeclared, a missing key refused.

    A ``[deploy]`` stating no root is at its grant's cluster root, read from the ``[hpc]`` of the family file the
    machine file names (:func:`~dev_lab.dev.hpcaccount.grantslice.machine_table`, ``granted_root``): the render a
    deploy leaves is all a tick reads. *root* is that root as the caller was handed it, for a hand-declared file
    naming no family (deploy-fleet's grant table, before the grant is written).
    """
    return parse(machine_table(path), path, root=root)


def parse(table: Mapping[str, Any], path: Path, *, root: str = '') -> Deployment | None:
    """The ``[deploy]`` of an already-read machine-file *table* (named *path* in a refusal); see :func:`load`."""
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
            root=_root(path, raw, root or granted_root(table.get('hpc'), table.get('devhost', {}).get('host', ''))),
            python=raw.get('python', DEFAULT_PYTHON),
            repos=tuple(
                Repo(r['name'], r['url'], r['ref'], tuple(r.get('verify', ())), _claims(path, r))
                for r in _repo_rows(path, raw['repos'])
            ),
            slurm_account=raw.get('slurm_account', ''),
            partitions=tuple(raw.get('partitions', ())),
            role=_role(path, raw.get('role', '')),
            tick=_tick(path, table.get('schedule', {})),
            tick_wall=_tick_wall(path, table.get('schedule', {})),
            env=_env(path, table.get('env', {})),
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


#: An ``[env]`` name: a shell variable, upper case by convention so it never shadows a shell's own.
_ENV_NAME: Final = re.compile(r'[A-Z_][A-Z0-9_]*')


def _env(path: Path, table: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    """``[env]``: this account's own tool paths (``FEMM_DIR = "~/opt/femm"``), each a string; else refused by name.

    The ONE home of a per-account variable (#621): a grant's ``setup`` is a family fact shared by every account of
    the cluster, so a per-account export there would be a second copy. A leading ``~/`` is the account's home.
    """
    bad = [
        f'{key} = {value!r}' for key, value in table.items() if not _ENV_NAME.fullmatch(key) or type(value) is not str
    ]
    if bad:
        msg = (
            f'[env] in {path}: {"; ".join(bad)} -- each name is a shell variable (A-Z, 0-9, _) and each value a string'
        )
        raise ValueError(msg)
    return tuple(sorted(table.items()))


def schedule_tick(schedule: Mapping[str, Any], where: str = '[schedule]') -> float:
    """``[schedule] tick`` in seconds (a duration, :mod:`lab_commons.quantity`), :data:`DEFAULT_TICK` when undeclared.

    The one reader of the period: the cron lines run at it, the host card is judged stale against it, and the tick's
    own readings use it as their cadence. A retired ``tick_minutes`` is refused with its new line.
    """
    refuse_renamed(where, schedule, SCHEDULE_RENAMED)
    if 'tick' not in schedule:
        return float(DEFAULT_TICK)
    return quantity.parse(f'{where} tick', schedule['tick'], 'duration', positive=True)


_MINUTE: Final = 60


def _whole_minutes(seconds: float) -> int | None:
    return int(seconds // _MINUTE) if seconds >= _MINUTE and seconds % _MINUTE == 0 else None


def _tick(path: Path, schedule: Mapping[str, Any]) -> int:
    """``[schedule] tick`` in seconds, as a cron step: whole minutes dividing the hour, else refused naming the key."""
    seconds = schedule_tick(schedule, f'{path}: [schedule]')
    minutes = _whole_minutes(seconds)
    if minutes is None or 60 % minutes:
        declared = schedule.get('tick')
        msg = f'{path}: [schedule] tick = {declared!r}: cron needs whole minutes dividing an hour, such as "15 min"'
        raise ValueError(msg)
    return int(seconds)


def _tick_wall(path: Path, schedule: Mapping[str, Any]) -> int:
    """``[schedule] tick_wall`` in seconds: a positive duration of whole minutes, else refused naming the key."""
    where = f'{path}: [schedule]'
    refuse_renamed(where, schedule, SCHEDULE_RENAMED)
    if 'tick_wall' not in schedule:
        return DEFAULT_TICK_WALL
    seconds = quantity.parse(f'{where} tick_wall', schedule['tick_wall'], 'duration', positive=True)
    if _whole_minutes(seconds) is None:
        declared = schedule['tick_wall']
        msg = f'{where} tick_wall = {declared!r}: declare whole minutes, such as "40 min" (the tick takes minutes)'
        raise ValueError(msg)
    return int(seconds)


def _repo_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> Sequence[Mapping[str, Any]]:
    """*rows*, refused naming *path* when one still declares the retired ``serve`` flag."""
    if named := [str(row.get('name', '?')) for row in rows if 'serve' in row]:
        msg = (
            f'{path}: [deploy] repos {", ".join(named)} declare serve, which is retired: a repo is served where the '
            'family binds one of its roles to the grant role of this account (dev_lab.dev.roles, D73) -- delete the key'
        )
        raise ValueError(msg)
    return rows


def _claims(path: Path, row: Mapping[str, Any]) -> str:
    """A row's ``claims``: one of :data:`CLAIMS`, ``''`` when undeclared; anything else refused naming the choices."""
    claims = row.get('claims', '')
    if claims != '' and claims not in CLAIMS:
        name = row.get('name', '?')
        msg = f'{path}: [deploy] repos {name} claims = {claims!r}: declare one of {list(CLAIMS)} or omit it'
        raise ValueError(msg)
    return str(claims)


def _unserved(repo: Repo) -> str:
    claims = f', claims = {_toml(repo.claims)}' if repo.claims else ''
    return (f', verify = {_list(repo.verify)}' if repo.verify else '') + claims


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
    """One marked line per served repo and the kit, every ``[schedule] tick``, each tick under its own lock.

    The minute offset is derived from *home* (one per account), so accounts sharing a forge tick staggered
    rather than in lockstep; an unserved repo other than the kit gets no line (:class:`Repo`).
    """
    step = spec.tick // 60
    minute = f'{zlib.crc32(str(home).encode()) % step}-59/{step}'
    return [
        f'{minute} * * * * {tick_command(spec, home, repo, log=True, slurm=slurm, setup=setup)} {MARK}{repo.name}'
        for repo in ticked(spec, serves=serves)
    ]


def ticked(spec: Deployment, *, serves: bool | None = None) -> tuple[Repo, ...]:
    """The repos this account TICKS: every declared one, each refreshed and served where a role is bound here.

    A tick serves a repo only where the family binds one of its roles to this account (:func:`serves_here`).

    Only an account whose role SERVES ticks -- *serves* as the workstation's role table says, else the shipped
    default for its role (:data:`dev_lab.dev.hpcaccount.division.DEFAULT_ROLES`); undeclared ticks nothing.
    """
    if not (DEFAULT_ROLES.get(spec.role, {}).get('serves', False) if serves is None else serves):
        return ()
    return spec.repos


def served(spec: Deployment) -> frozenset[str]:
    """The repos this account serves (:func:`serves_here`); malformed roles are not (its tick names why)."""
    found = set()
    for repo in spec.repos:
        try:
            if serves_here(spec, repo):
                found.add(repo.name)
        except Unbound:
            continue
    return frozenset(found)


def unserved(spec: Deployment) -> frozenset[str]:
    """The repos with no role bound to this account: never served here, never given the token.

    The family's binding of the repo's URL decides (:func:`~dev_lab.dev.roles.roles_of_url`), never whether a
    checkout exists: the credentials phase runs before the first clone, so on a fresh root every repo the family
    binds elsewhere (hosted CI) read as served and was refused for a credential nothing there uses (measured
    2026-11-22). A repo whose roles are unbound stays checked: its tick names why.
    """
    found = set()
    for repo in spec.repos:
        try:
            if not _bound_here(spec, roles_of_url(repo.url)):
                found.add(repo.name)
        except Unbound:
            continue
    return frozenset(found)


def _bound_here(spec: Deployment, roles: Roles) -> bool:
    """Whether *roles* binds a role to this account's grant role; a carried binding names kinds only (``''``)."""
    return any(roles.kind(role) == HPC and roles.of(role).grant_role in {spec.role, ''} for role in ROLES)


def serves_here(spec: Deployment, repo: Repo) -> bool:
    """Whether this account serves *repo*'s queue: the family binds one of its roles to this account's grant role.

    The family's binding decides (:mod:`dev_lab.dev.roles`, D73), never this file; not yet cloned, no.

    Raises:
        Unbound: the family binds the repo's roles nowhere, or malformed; the message names the table.

    """
    checkout = checkout_of(spec, repo)
    if not (checkout / 'pyproject.toml').is_file():
        return False
    return _bound_here(spec, roles_at(checkout))


def merge_crontab(current: str, lines: Sequence[str]) -> str:
    """*current* without any line this tool marked, plus *lines*; every other line kept in place."""
    kept = [line for line in current.splitlines() if MARK not in line]
    text = '\n'.join([*kept, *lines])
    return text + '\n' if text else ''


def tick_command(
    spec: Deployment, home: Path, repo: Repo, *, log: bool, slurm: Sequence[str] = (), setup: Sequence[str] = ()
) -> str:
    """The shell command of one tick of *repo*: :func:`tick_environment`, then the HOST's ``hpcaccount tick``.

    The tick takes its own lock, ``<serve>/<repo>.lock``, and runs within ``[schedule] tick_wall``
    (:mod:`dev_lab.dev.hpcaccount.tickwall`): the lock names its holder, which ``flock -n`` could not.

    It runs from the kit (dev-lab) checkout's venv, never the repo's: the host refreshes the repo (and
    itself), then serves it with its own kit (:func:`host_serve_argv`), so a stale repo venv blocks nothing.
    With a grant *setup* the whole tick runs in ONE ``bash -lc`` (``module`` is a login-shell function), so
    every tool it loads runs inside the environment that loaded it -- a module's binary does not run outside
    it (Ada 2026-10-17: git 2.42 alone wants ``libiconv.so.2``).
    """
    serve = Path(paths_of(spec, serves=True).root) / 'serve'
    lab = next(one for one in spec.repos if one.name == KIT)
    command = (
        f'{tick_environment(home, spec.root, slurm, setup, spec.env)}; '
        f'cd {shlex.quote(str(checkout_of(spec, lab)))} && '
        f'{shell_interpreter(".")} -m dev_lab.dev.hpcaccount tick {shlex.quote(repo.name)} '
        f'--lock {shlex.quote(str(serve / f"{repo.name}.lock"))} --wall-minutes {spec.tick_wall // 60}'
    )
    command = f'bash -lc {shlex.quote(command)}' if setup else command
    return command + (f' >> {shlex.quote(str(serve / f"{repo.name}.log"))} 2>&1' if log else '')


def tick_environment(
    home: Path,
    root: str,
    slurm: Sequence[str] = (),
    setup: Sequence[str] = (),
    env: Sequence[tuple[str, str]] = (),
) -> str:
    """The shell prefix of a tick's environment: cron's PATH, the account root, its *env*, then the grant *setup*.

    PATH is :func:`tick_dirs`; ``LAB_ROOT`` is the declared *root* every remote script of :mod:`lab_commons.hpc` names
    (cron reads no login profile); *env* is the account's ``[env]``, exported so every job the tick submits inherits
    it. The ONE definition of that environment: the cron line runs it, and the deploy proves the tick's git in it.
    """
    pairs = [
        (ROOT_VAR, root),
        ('UV_CACHE_DIR', str(uv_cache(root))),
        *((key, _homed(home, value)) for key, value in env),
    ]
    exported = 'export ' + ' '.join(f'{key}={shlex.quote(value)}' for key, value in pairs) + ' UV_LINK_MODE=hardlink'
    return '; '.join([f'PATH={":".join(tick_dirs(home, slurm))}', exported, *setup])


def _homed(home: Path, value: str) -> str:
    """*value* with a leading ``~/`` made the account's *home* (a quoted ``~`` never expands in a shell)."""
    return str(home / value[2:]) if value.startswith('~/') else value


def uv_cache(root: str) -> Path:
    """The account's ONE uv cache, ``<root>/cache/uv``: every uv the kit runs there shares it, every env hardlinks it.

    It lives under the declared root, on the same filesystem as the envs it links into, so a hardlink never falls
    back to a copy. uv's own default (``~/.cache/uv``) is retired: a second cache doubled an account's files
    (census 2026-11-14), and retention removes it (:func:`dev_lab.dev.retentionplan`).
    """
    return Path(paths_of_root(root).root) / 'cache' / 'uv'


def tick_dirs(home: Path, slurm: Sequence[str] = ()) -> list[str]:
    """The directories of a tick's PATH, in order: cron's own PATH is not the login shell's.

    *slurm* is where ``sbatch``, ``sacct`` and ``squeue`` resolved when the deploy ran -- a site install
    (``/opt/slurm/<version>/bin``) that cron's PATH never names. A tool the grant's ``setup`` loads is never
    named here: it runs inside that setup (:func:`tick_environment`).
    """
    base = [str(home / '.local/bin'), str(home / '.cargo/bin'), '/usr/local/bin', '/usr/bin', '/bin']
    return [*base, *(d for d in dict.fromkeys(slurm) if d not in base)]


def paths_of_root(root: str, *, serves: bool = False) -> AccountPaths:
    """The account layout under a declared *root* (:func:`lab_commons.hpc.layout.account_paths`)."""
    return account_paths(root, serves=serves)


def paths_of(spec: Deployment, *, serves: bool) -> AccountPaths:
    """*spec*'s account layout; the serving directories only when the account *serves*."""
    return paths_of_root(spec.root, serves=serves)


def checkout_of(spec: Deployment, repo: Repo) -> Path:
    """Where *repo* is checked out: ``<root>/repos/<name>`` under the account's declared root."""
    return Path(paths_of(spec, serves=False).repo(repo.name))


def _root(path: Path, raw: Mapping[str, Any], granted: str = '') -> str:
    """The declared ``[deploy] root``, else the *granted* cluster root; absolute, else refused."""
    try:
        return account_paths(raw.get('root') or granted, serves=False, account=str(path)).root
    except RootUndeclared as refused:
        raise ValueError(str(refused)) from None


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
