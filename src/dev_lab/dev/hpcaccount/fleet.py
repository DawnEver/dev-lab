"""``python -m dev_lab.dev.hpcaccount deploy-fleet [--account <user>]... [--dry-run]`` -- deploy every declared account.

THE FLEET IS THE MACHINE FILE'S ``[[hpc.grant]]`` TABLES (:func:`lab_commons.hpc.grants.load_grants`), the one
source the forge's submits read too; nothing here lists an account. Each ``--account`` named must be in the
fleet -- anything else is refused before any ssh.

WHERE AN ACCOUNT SERVES IS ITS LAYER'S DECLARATION, never this machine's guess and never the account's rendered
machine file: the ``[deploy]`` ``host``, ``root`` and ``repos`` of ``hosts/<cluster>-<user>.toml`` in this
workstation's config-source clone (:func:`layer_target`). The account's own file may be stale; the render below
overwrites it, so a stale remote ``[deploy]`` is never read and never refuses. Its ``role`` is printed per account.
A layer with no ``[deploy]`` host, or whose host is not one of its grant's login hosts, is refused by name and the
others still deploy (exit 2).

AN ACCOUNT WITH NO KIT VENV IS FIRST INSTALLED (:func:`first_install`): a key-only account has no other door, so
when ``~/<root>/dev-lab/.venv`` has no interpreter, uv is installed into ``~/.local/bin`` if absent, the
kit is cloned where missing (only the kit: a forge-hosted repo needs the reader credential placed later), and the
kit is ``uv sync --frozen``-ed; a kit with its venv skips the step.

THE ROLE IS THE WORKSTATION'S (user rulings 2026-11-09): each grant's ``role`` and the ``[hpc.roles]`` table
(:mod:`dev_lab.dev.hpcaccount.division`) are passed to the account's deploy, which refuses when its own ``[deploy]
role`` differs, naming both. A grant role the table does not name is refused here, before any ssh.

Then it runs, through the one transport (:mod:`~dev_lab.dev.hpcaccount.transport`: the dest's held session when
one is live, else ONE detached ``ssh -o BatchMode=yes <user>@<declared host>``), that account's own
``python -m dev_lab.dev.hpcaccount deploy`` in ``~/<root>/dev-lab`` -- after the kit's own tick has
refreshed that checkout (:func:`refresh_kit`; with the layer's kit ref, a direct fast-forward under the tick's lock,
since the tick reads the stale machine file), so a fix to the deploy reaches an account that never ticks --
and writes everything it prints to one log
per account (``~/.cache/dev-lab/<yy>/<mm>/<dd>/deploy-fleet/<user>.log``). The deploy is safe to repeat.

THE ACCOUNT RENDERS ITS OWN LAYER FIRST (user ruling 2026-11-15: FAMILY -> ACCOUNT -> LOCAL, one road). Its machine
file is the render of the config source's ``family.toml`` and ``hosts/<cluster>-<user>.toml``
(:mod:`dev_lab.dev.accounthost`), and that render runs ON the account, so it runs here, between the kit's tick and
the deploy (:func:`render_command`): the account clones or fast-forwards the config source (THIS workstation's
``[devhost]`` clone's origin, :class:`ConfigSource`) with its stored reader credential -- none stored for that forge
is refused naming ``hpcaccount credential`` -- prints ``devhost drift --from`` that clone (what the render
changes), then ``devhost render --write`` (the old file backed up under ``~/.cache/dev-lab/<yy>/<mm>/<dd>/devhost``).
A failed render stops that account's deploy. Before any ssh, an account whose grant names no cluster, whose
``<cluster>-<user>`` the family file declares no grant for, or whose ``hosts/<cluster>-<user>.toml`` this
workstation's clone lacks, is refused by name (:func:`layer_refusal`).
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import IO, Any, Final
from urllib.parse import urlsplit

from lab_commons import config as machineconfig
from lab_commons import home as _home
from lab_commons.config import CONFIG_ENV
from lab_commons.hpc.cluster import Runner
from lab_commons.hpc.grants import Grant
from lab_commons.log import emit

from dev_lab.dev import accounthost
from dev_lab.dev.credstore import STORE, valid_host
from dev_lab.dev.datedlog import dated_log
from dev_lab.dev.devdeclared import OWN_TABLE
from dev_lab.dev.devhost import host_file
from dev_lab.dev.devsource import config_source
from dev_lab.dev.hpcaccount.cimark import paused_guard
from dev_lab.dev.hpcaccount.division import Division, division_of, reached_machine
from dev_lab.dev.hpcaccount.fleetguard import serving_twice_refusal, stale_render
from dev_lab.dev.hpcaccount.spec import KIT, paths_of_root
from dev_lab.dev.hpcaccount.transport import describe, start
from dev_lab.dev.machinehome import default_layout
from dev_lab.dev.venvpointer import shell_interpreter

__all__ = [
    'KIND', 'ConfigSource', 'Target', 'account_clone', 'account_host', 'config_source_of', 'declared_target',
    'deploy_command', 'deploy_fleet', 'first_install', 'in_checkout', 'layer_refusal', 'layer_target', 'main',
    'refresh_kit', 'render_command',
]  # fmt: skip

#: The dated-log kind every account's log is written under.
KIND: Final = 'deploy-fleet'
_BASE: Final = '.cache/dev-lab'


_MACHINE_HOME, _CONFIG_UNDER_HOME = default_layout()

#: The account's machine file as ITS python resolves it (:func:`lab_commons.config.config_path`): the override, else
#: the machine home's file. Prints ``# <path>`` first, so a refusal names the file it looked in.
_MACHINE_FILE: Final = f'"${{{CONFIG_ENV}:-${{{_home.HOME_ENV}:-$HOME/{_MACHINE_HOME}}}/{_CONFIG_UNDER_HOME}}}"'
_READ_DEPLOY: Final = f'f={_MACHINE_FILE}; echo "# $f"; ' + 'sed -n \'/^\\[deploy\\]/,/^\\[/p\' "$f" 2>/dev/null; true'

#: Runs one deploy on a dest: ``(dest, command, log) -> object`` (:func:`dev_lab.dev.hpcaccount.transport.start`).
Launch = Callable[[str, str, IO[Any]], object]


@dataclass(frozen=True)
class Target:
    """Where one account deploys: its declared login host, checkout root and role (``''``: undeclared)."""

    host: str
    root: str
    role: str = ''
    repos: tuple[tuple[str, str, str], ...] = ()  # (name, https url, ref): what a first install clones


def declared_target(grant: Grant, shell: Runner, *, as_deployed: bool = False) -> Target | str:
    """*grant*'s ``[deploy]`` host and root as its REMOTE machine file declares them, read through *shell*.

    The read for the doors that act on an account as it stands (credential, forget, storage). deploy-fleet never
    reads it: a fleet account's ``[deploy]`` is its layer's (:func:`layer_target`), which the deploy renders over a
    stale remote file.

    *as_deployed* takes the root the account was deployed at even when the cluster now declares another: the
    credential door acts on the checkout as it stands, and its store (``~/.git-credentials``) is home-level, so a
    stale root never blocks the credential the redeploy to the new root needs (measured 2026-11-20: a deadlock).
    """
    out = shell(_READ_DEPLOY, None).splitlines()
    looked = next((line[2:] for line in out if line.startswith('# ')), 'its machine file')
    lines = [line for line in out if not line.startswith('#')]
    table = '\n'.join(lines[:1] + [line for line in lines[1:] if not line.startswith('[')])
    deploy = tomllib.loads(table).get('deploy', {}) if table.strip() else {}
    return _checked(grant, deploy, looked, 'deploy it once by hand', as_deployed=as_deployed)


def layer_target(grant: Grant, source: ConfigSource) -> Target | str:
    """*grant*'s ``[deploy]`` from its account layer ``hosts/<cluster>-<user>.toml`` in *source* -- the one source.

    Read on THIS workstation, never from the account: its rendered machine file may be stale, and the deploy renders
    this layer over it (:func:`render_command`). The layer's declared repos ride along for a first install.
    """
    path = source.clone / host_file(account_host(grant))
    deploy = tomllib.loads(path.read_text(encoding='utf-8')).get('deploy', {})
    return _checked(grant, deploy, str(path), 'declare it there')


def _checked(
    grant: Grant, deploy: Mapping[str, Any], looked: str, door: str, *, as_deployed: bool = False
) -> Target | str:
    """The target *deploy* (read from *looked*) declares for *grant*; else why it cannot be deployed.

    The host may name a grant login host in full or by its first DNS label (``login01``); a label resolves
    to the ONE full host it names, and a label two login hosts share is refused rather than the first kept.
    """
    host = deploy.get('host', '')
    if not host:
        return f'{grant.user}: refused -- no [deploy] host in {looked}; {door}'
    named = [login for login in grant.hosts if host in {login, login.split('.', 1)[0]}]
    if not named:
        return f'{grant.user}: refused -- its [deploy] host {host} is not a login host of its grant {list(grant.hosts)}'
    if len(named) > 1:
        return f'{grant.user}: refused -- its [deploy] host {host} is ambiguous: it names {named}; declare one in full'
    root = deploy.get('root', grant.root)  # an unstated root is the cluster's: declared, never a default
    if not root:
        return (
            f'{grant.user}: refused -- no root declared: declare [hpc.clusters.{grant.cluster_name}] root (or the '
            f"account file's [deploy] root) in the family config, on a filesystem the compute nodes see"
        )
    relative = not str(root).startswith('/')
    if as_deployed and relative:  # the pre-root layout: home-relative, its checkouts at ~/<root>/<name>
        root = f'~/{str(root).removeprefix("~/")}'
    elif relative or (grant.root and root != grant.root and not as_deployed):
        why = (
            'must be an absolute path (a declared root, never ~)'
            if relative
            else f'is not the root its cluster declares {grant.root} (the family declaration is the source: '
            'redeploy with --root naming it)'
        )
        return f'{grant.user}: refused -- its [deploy] root {root} {why}'
    repos = tuple((r['name'], r['url'], r['ref']) for r in deploy.get('repos', ()) if {'name', 'url', 'ref'} <= set(r))
    return Target(named[0], root, deploy.get('role') or grant.role, repos)  # unstated: the family grant's role


@dataclass(frozen=True)
class ConfigSource:
    """The config source an account renders from: this workstation's clone (its files) and that clone's origin."""

    clone: Path
    url: str


def config_source_of(live: Mapping[str, Any]) -> ConfigSource:
    """The workstation's config source, from its machine file's ``[devhost]`` (:func:`devsource.config_source`).

    Raises:
        ValueError: the machine file is not a render, or its clone's ``origin`` is absent or not an https url.

    """
    url = config_source(live)
    if urlsplit(url).scheme != 'https' or not valid_host(urlsplit(url).hostname or ''):
        msg = f'the config source {url} is not an https forge url: an account reads it with its stored reader token'
        raise ValueError(msg)
    return ConfigSource(Path(live[OWN_TABLE]['source']), url)


def account_host(grant: Grant) -> str:
    """The host-file name of *grant*'s account: ``<cluster>-<user>`` (:mod:`dev_lab.dev.accounthost`)."""
    return f'{grant.cluster_name}-{grant.user}'


def layer_refusal(grant: Grant, source: ConfigSource) -> str:
    """Why *grant*'s account cannot render its layer from *source*; ``''`` when it can. Read here, before any ssh."""
    name, family_file = account_host(grant), source.clone / 'family.toml'
    if not grant.cluster_name:
        return f'{grant.user}: refused -- its [[hpc.grant]] names no cluster, so it has no account file to render'
    family = tomllib.loads(family_file.read_text(encoding='utf-8')) if family_file.is_file() else {}
    if accounthost.grant_of(name, family) is None:
        return (
            f'{grant.user}: refused -- {family_file} declares no [[hpc.grant]] with cluster {grant.cluster_name!r} '
            f'and user {grant.user!r}: declare the grant in the family file'
        )
    if not (source.clone / host_file(name)).is_file():
        return (
            f'{grant.user}: refused -- {source.clone} has no {host_file(name)}: declare the account file there '
            '(dev_lab.dev.accounthost)'
        )
    return ''


def render_command(grant: Grant, target: Target, source: ConfigSource, *, reader: str = '') -> str:
    """The shell line that renders *grant*'s machine file ON its account from the config source's clone there.

    The clone is ``<root>/repos/<config repo>``, fetched with the account's stored credential (refused, naming the door
    that places one, when none is stored for the forge); ``devhost drift`` prints what the render changes, then
    ``devhost render --write`` replaces the file, its old copy backed up. In the grant's ``setup`` environment.
    With *reader* (the role's ``config_reader``), the url names that login, so git's store answers with ITS line
    even when the account holds another login's line for the same forge (one line per host and login, 2026-11-20).
    """
    split = urlsplit(source.url)
    forge = split.hostname or ''
    url = split._replace(netloc=f'{reader}@{split.netloc}').geturl() if reader else source.url
    clone = shlex.quote(account_clone(target, source).as_posix())
    backups = f'"$HOME/{_BASE}/$(date -u +%y/%m/%d)/devhost"'
    held = f'://{reader}:[^@/]*@{forge}' if reader else f'@{forge}'
    credential = (
        f"grep -qs '{held}' ~/{STORE} || {{ echo '[render] refused -- no stored reader credential for {forge} in "
        f'~/{STORE}: place one with python -m dev_lab.dev.hpcaccount credential {grant.user}@{target.host} --login '
        f"{reader or '<reader>'} --host-config <config source clone>'; exit 2; }}"
    )
    quoted = shlex.quote(url)
    fetch = (
        f'if [ -d {clone}/.git ]; then git -C {clone} remote set-url origin {quoted} '
        f'&& git -C {clone} pull -q --ff-only; '
        f'else git clone -q {quoted} {clone}; fi'
    )
    name = account_host(grant)
    drift = in_checkout(target, ['-m', 'dev_lab.dev.devhost', 'drift'])
    render = in_checkout(target, ['-m', 'dev_lab.dev.devhost', 'render', '--host', name, '--write'])
    steps = [
        'export GIT_TERMINAL_PROMPT=0', credential, fetch, f'echo "[render] {name}: what the render changes"',
        f'{{ {drift} --from {clone} ; true; }}', f'{render} --from {clone} --backups {backups}',
    ]  # fmt: skip
    return f'( {" && ".join([*grant.setup, *steps])} )'


def repo_dir(target: Target, name: str) -> PurePosixPath:
    """*target*'s checkout of *name*: ``<root>/repos/<name>`` (:mod:`lab_commons.hpc.layout`).

    A ``~/`` root is an account deployed before the declared root (only :func:`declared_target`'s *as_deployed*
    read yields one): its checkouts sit at ``~/<root>/<name>``, the layout it was deployed with.
    """
    if target.root.startswith('~/'):
        return PurePosixPath(target.root, name)
    return PurePosixPath(paths_of_root(target.root).repo(name))


def account_clone(target: Target, source: ConfigSource) -> PurePosixPath:
    """Where *target*'s account holds its config-source clone: ``<root>/repos/<config repo>``."""
    return repo_dir(target, PurePosixPath(urlsplit(source.url).path).stem)


def in_checkout(target: Target, argv: Sequence[str]) -> str:
    """The shell line that runs ``python <argv>`` in *target*'s declared dev-lab checkout, with its venv."""
    kit = repo_dir(target, KIT)  # every cluster login host is POSIX
    return f'cd {kit} && {shell_interpreter(".")} {shlex.join(argv)}'


def grant_slice(grant: Grant) -> dict[str, Any]:
    """*grant* as the ``[hpc]`` slice its account's own machine file holds: its cluster, its grant, its role reached."""
    account: dict[str, Any] = {'billed': grant.billed}
    if grant.budget is not None:
        account['budget'] = {'core_hours': grant.budget.core_hours, 'since': grant.budget.since}
    cluster: dict[str, Any] = {'hosts': list(grant.hosts), 'slurm_accounts': {grant.slurm_account: account}}
    optional = {
        'partitions': list(grant.partitions), 'qos': dict(grant.qos), 'setup': list(grant.setup),
        'architecture': grant.architecture, 'root': grant.root,
    }  # fmt: skip
    cluster.update({key: value for key, value in optional.items() if value})
    row = {'user': grant.user, 'cluster': grant.cluster_name, 'slurm_account': grant.slurm_account, 'role': grant.role}
    row.update({key: value for key, value in (('owner', grant.owner), ('priority', grant.priority)) if value})
    return {'reach': [grant.role], 'clusters': {grant.cluster_name: cluster}, 'grant': [row]}


def deploy_command(grant: Grant, target: Target, source: ConfigSource, division: Division | None = None) -> str:
    """The shell line that runs *grant*'s own deploy on its DECLARED host (:mod:`dev_lab.dev.hpcaccount.transport`).

    After the kit's tick the account renders its own layer from *source* (:func:`render_command`); only a render that
    succeeds deploys. The deploy is passed its declared ``[hpc]`` slice (:func:`grant_slice`); with *division*, also
    the role and its table.
    """
    deploy = ['-m', 'dev_lab.dev.hpcaccount', 'deploy', '--grant-table', json.dumps(grant_slice(grant), sort_keys=True)]
    if division is not None and (role := division.role_of(grant.user)):
        deploy += ['--fleet-role', role, '--role-table', json.dumps(dict(division.roles[role]), sort_keys=True)]
    refreshed = f'{first_install(grant, target)} && {refresh_kit(grant, target)}'
    reader = division.config_reader(grant.user) if division is not None else ''
    deployed = in_checkout(target, deploy)
    if grant.setup:  # the venvs it builds compile in the cluster's declared environment, as its ticks run
        deployed = f'( {" && ".join([*grant.setup, deployed])} )'
    rendered = render_command(grant, target, source, reader=reader)
    return f'{paused_guard(target.root)} && {refreshed} ; {rendered} && {deployed}'


#: The official uv installer (user approval 2026-11-16: an HPC account may install uv into ``~/.local/bin``).
UV_INSTALLER: Final = 'https://astral.sh/uv/install.sh'


def first_install(grant: Grant, target: Target) -> str:
    """The shell line that gives *target* a kit venv when it has none, else does nothing.

    A key-only account has no door for a first install (raw ssh is refused), and every later step runs the kit's
    venv python. So, only when that interpreter is missing: uv into ``~/.local/bin`` unless one is on PATH, each
    declared repo cloned at its ref where its checkout is absent, then ``uv sync --frozen`` in the kit.
    """
    root = PurePosixPath(paths_of_root(target.root).root) / 'repos'
    kit = root / KIT
    clones = [  # the kit alone: a forge-hosted product repo needs a reader credential the deploy places later
        f'{{ [ -d {root / name}/.git ] || git clone -q --branch {shlex.quote(ref)} {shlex.quote(url)} {root / name}; }}'
        for name, url, ref in target.repos
        if name == KIT
    ]
    steps = [
        f'echo "[first-install] {grant.user}: no kit venv in {kit}"',
        'export PATH="$HOME/.local/bin:$PATH" GIT_TERMINAL_PROMPT=0',
        f'{{ command -v uv >/dev/null || curl -LsSf {UV_INSTALLER} | env UV_NO_MODIFY_PATH=1 sh; }}',
        f'mkdir -p {root}', *clones, f'( cd {kit} && uv sync --frozen )',
    ]  # fmt: skip
    body = ' && '.join([*grant.setup, *steps])
    return f'{{ [ -x {shell_interpreter(str(kit))} ] || ( {body} ); }}'


def refresh_kit(grant: Grant, target: Target) -> str:
    """The shell line that brings *target*'s kit to its declared tip BEFORE the deploy runs, and records the sha.

    A dead account cannot heal itself: its kit moves only on its own cron tick, which never runs, so a fix to
    ``deploy`` would never reach it. The step is the kit's OWN tick (:mod:`dev_lab.dev.hpcaccount.tick`, the one
    writer of the host checkout), never a second refresh; in the grant's ``setup`` environment, as the cron line
    runs it (:func:`dev_lab.dev.hpcaccount.spec.tick_command`). The deploy follows whatever the tick exits: a
    research kit refreshes, then refuses to serve.
    """
    kit = repo_dir(target, KIT)
    recorded = f'echo "[deploy-fleet] kit at $(git -C {kit} rev-parse HEAD)"'
    ref = next((ref for name, _url, ref in target.repos if name == KIT), '')
    tick = f'{in_checkout(target, ["-m", "dev_lab.dev.hpcaccount", "tick", KIT])} ; {recorded}'
    if ref:
        tick = f'{_move_kit(kit, ref)} ; {recorded}'
    return f'bash -lc {shlex.quote("; ".join([*grant.setup, tick]))}' if grant.setup else tick


def _move_kit(kit: PurePosixPath, ref: str) -> str:
    """The kit fast-forwarded to its LAYER-declared *ref* and its own venv re-synced, under the cron tick's lock.

    Never through the kit's tick: that reads the account's machine file, which is the stale thing this deploy is
    about to render over (2026-11-20: a retired key crashed it before it refreshed; an old root sent it to another
    checkout). The lock is the cron tick's, so the kit keeps one writer at a time.
    """
    remote = f'refs/remotes/origin/{ref}'
    python = shell_interpreter('.')
    body = ' && '.join([
        f'git fetch -q origin {shlex.quote(f"+refs/heads/{ref}:{remote}")}',
        f'git checkout -q -B {shlex.quote(ref)} {shlex.quote(remote)}',
        f'py={python}',
        'UV_PROJECT_ENVIRONMENT="${py%/bin/python}" uv sync --frozen',
    ])  # fmt: skip
    serve = kit.parent.parent / 'serve'  # <root>/repos/dev-lab -> <root>/serve: the cron tick's own lock
    lock = serve / f'{KIT}.lock'
    return (
        f'( export PATH="$HOME/.local/bin:$PATH" GIT_TERMINAL_PROMPT=0; mkdir -p {serve}; cd {kit} && '
        f'flock -w 600 {lock} bash -c {shlex.quote(body)} )'
    )


def _target(grant: Grant, source: ConfigSource, division: Division | None) -> Target | str:
    """Where *grant*'s account deploys; else why it is refused (its role, its layer, then its declared host)."""
    if division is not None and (why := division.refusal(grant.user)):
        return f'{why}; refused'
    if why := layer_refusal(grant, source):
        return why
    try:
        return layer_target(grant, source)
    except (OSError, tomllib.TOMLDecodeError) as failed:
        return f'{grant.user}: refused -- its layer [deploy] could not be read: {failed}'


def deploy_fleet(
    grants: Sequence[Grant],
    accounts: Sequence[str],
    *,
    home: Path,
    source: ConfigSource,
    dry_run: bool,
    say: Callable[[str], None],
    launch: Launch = start,
    division: Division | None = None,
) -> int:
    """Start each account's deploy on its declared host; 2 when any account was refused."""
    if why := serving_twice_refusal(grants, accounts, division):
        say(f'deploy-fleet: refused -- {why}')
        return 2
    fleet: dict[str, Grant] = {}
    for grant in grants:  # a non-serving account's further grants are allocations, not hosts: its first one deploys
        fleet.setdefault(grant.user, grant)
    if unknown := sorted(set(accounts) - set(fleet)):
        say(f'deploy-fleet: refused -- {unknown} not in the declared fleet {sorted(fleet)}')
        return 2
    if not fleet:
        say('deploy-fleet: refused -- the machine file declares no [[hpc.grant]]')
        return 2
    refused = 0
    for user in accounts or sorted(fleet):
        grant = fleet[user]
        path = dated_log(home, f'{user}.log', base=_BASE, kind=KIND)
        target = _target(grant, source, division)
        if isinstance(target, str):
            say(target)
            _log_line(path, target, dry_run=dry_run)
            refused += 1
            continue
        dest, command = f'{grant.user}@{target.host}', deploy_command(grant, target, source, division)
        role = (division.role_of(user) if division else '') or target.role or 'role undeclared'
        said = f'{user} ({role}): {"would start" if dry_run else "started"} {describe(dest, command)}  log {path}'
        say(said)
        _log_line(path, said, dry_run=dry_run)
        if not dry_run:
            with path.open('a', encoding='utf-8') as log:
                try:
                    launch(dest, command, log)
                except (RuntimeError, OSError) as failed:  # HoldRefused is a RuntimeError
                    log.write(f'[deploy-fleet] {user}: refused before the deploy ran -- {failed}\n')
                    say(f'{user}: refused -- {failed}')
                    refused += 1
    return 2 if refused else 0


def _log_line(path: Path, line: str, *, dry_run: bool) -> None:
    """Write *line* to the account's dated deploy log FIRST, so an early exit still leaves its log.

    Measured 2026-11-20: two accounts' runs left no log at all. A dry run writes nothing.
    """
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as log:
            log.write(f'[deploy-fleet] {line}\n')


def main(argv: Sequence[str] | None = None) -> int:
    """Parse ``deploy-fleet`` and start it."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount deploy-fleet', description=__doc__.splitlines()[0])
    parser.add_argument('--account', action='append', default=[], help='one account of the fleet (repeatable)')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        machine = reached_machine(args.account)
        live = machineconfig.machine()
        source = config_source_of(live)
    except (PermissionError, LookupError, ValueError) as refused:
        emit(f'deploy-fleet: refused -- {refused}')
        return 2
    if why := stale_render(live):
        emit(f'deploy-fleet: refused -- {why}')
        return 2
    return deploy_fleet(
        machine.grants,
        args.account,
        home=Path.home(),
        source=source,
        dry_run=args.dry_run,
        say=emit,
        division=division_of(machine),
    )
