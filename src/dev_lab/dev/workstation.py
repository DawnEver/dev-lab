"""A WINDOWS WORKSTATION AS A ``forge serve`` HOST, in one run: ``python -m dev_lab.dev.workstation deploy``.

The counterpart of a cluster account's ``python -m dev_lab.dev.hpchost deploy``, and it reuses that
deploy's run-or-print :class:`~dev_lab.dev.hpchost.steps.Step`.

``deploy --repos dev-lab,<repo>,... --capabilities workstation,jmag:4 [--seat-margin jmag=2]
[--cpu-margin N] [--mem-margin F] [--forge <https base>] [--root DIR] [--ref BRANCH] [--dry-run]``, each step
reporting and safe to repeat:

1. PROBE: ``uv`` and ``git`` on PATH; ``node`` when the ``node`` capability is declared; JMAG Designer and
   its Scheduler COM classes when ``jmag`` is. Every missing item is refused at once, each with its remedy.
2. CREDENTIAL: ``git ls-remote`` of every repo with prompting off, so only a STORED git credential
   answers; none is ever read or printed. A refusal names the one manual step.
3. CHECKOUTS under ``--root`` (default ``~/src``): clone ``<forge>/<repo>.git`` at ``--ref``,
   or fast-forward an existing CLEAN checkout to its upstream; a dirty one is refused.
4. VENVS: ``-m dev_lab.dev.dep --bootstrap <checkout>`` when the venv is missing or its ``pyproject.toml``
   or ``uv.lock`` changed since its last sync (a stamp in the venv, written only after a sync succeeds).
5. HOOKS: ``-m dev_lab.dev.hook_install --install`` in each checkout whose hooks are not live.
6. MACHINE FILE (:mod:`lab_commons.config`): ``[capabilities.<name>]`` (``seats`` from ``name:N``; a ``jmag``
   row also ``in_use = { process = JMAG_SOLVER_IMAGES }``, so a solve a person starts is a seat taken),
   ``[reserve]`` with each margin given (``cpu_margin``, ``mem_margin``, ``seat_margin``) and
   ``[serve] repos, root`` merged in place; every other table, key and comment is kept, and
   ``--dry-run`` prints the diff.
7. TASK: the one ``lab-forge-serve`` Scheduled Task (:mod:`dev_lab.dev.servetask`), registered from
   its XML definition and rewritten only when the installed one reads back different.

``--dry-run`` reads but changes nothing. A second run changes nothing.

A REFUSAL IN STEPS 3-5 BELONGS TO ITS REPO (incident 2026-10-13, the cluster deploy's twin): the repo is
reported with its reason, skipped by the later steps and left out of ``[serve] repos`` so the Task never
serves it; the deploy finishes for the others, raises one forge ``run`` alarm per refused repo
(:mod:`dev_lab.dev.forgealarm`), and exits 2 naming each.

``serve`` IS THE TASK'S ACTION: under the per-user serve lock (:mod:`dev_lab.dev.servelock`),
dev-lab and then each ``[serve] repos`` entry is REFRESHED BY THE HOST -- fast-forwarded to its
upstream and its venv synced when step 4 says so -- and only then THE HOST KIT runs ``forge serve`` in its
checkout (:func:`~dev_lab.dev.hpchost.spec.host_serve_argv`); the repo's venv only runs its producers.
The host owns the refresh because a repo's own kit cannot (incident 2026-10-13: a venv whose
old ``forge serve`` exited 2 every tick could never run the code that would update it). A repo whose
refresh fails is released with its reason in the serve log. Its exit is the worst child's; one repo's
failure never skips the next. Each child starts with no
console window; under ``pythonw`` (no streams at all) the serve and its children write to the capped
serve log (:func:`dev_lab.dev.servetask.open_log`).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Final

import lab_commons.launch as _door
from lab_commons.box.machine import provided
from lab_commons.compute.durable import durable_text
from lab_commons.config import config_path, section
from lab_commons.hpc.retired import refusal
from lab_commons.log import emit

from dev_lab.dev import servetask
from dev_lab.dev._machinefile import diff, merged
from dev_lab.dev.forgealarm import RUN, Alarm, sound
from dev_lab.dev.forgeclaim import DEFAULT_LEASE
from dev_lab.dev.forgeintent import journaled, reattach
from dev_lab.dev.forgework import client_for
from dev_lab.dev.hostrefresh import Moved, follow, network, read, refresh, sync_venv, venv_python
from dev_lab.dev.hpchost.spec import KIT, host_serve_argv
from dev_lab.dev.hpchost.steps import Step, Tools
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.servelock import default_lock, held

if sys.platform == 'win32':
    import winreg

__all__ = [
    'FORGE_ROLE',
    'JMAG_PROGIDS',
    'JMAG_SOLVER_IMAGES',
    'REGISTRY_TABLE',
    'WORKSTATION',
    'NoRegistry',
    'Programs',
    'com_server',
    'deploy',
    'forge_refusal',
    'main',
    'serve',
]

#: The resource a developer workstation provides: the live checkout and the agent tooling its guards run on.
#: ONE resource, not three: every host carrying the checkout, ``node`` or ``codex`` carries all of them, and the
#: cluster none, so a split would only queue one host's work as several parts (user directive 2026-10-19).
WORKSTATION: Final = 'workstation'
#: What a ``workstation`` declaration promises on ``PATH`` -- probed at deploy, so the declaration cannot lie.
_WORKSTATION_KIT: Final = ('node', 'codex')

#: The COM classes a ``jmag`` host drives: the Designer and its Scheduler.
JMAG_PROGIDS: Final = ('designer.Application', 'scheduler.JobApplication')

#: The images whose running count is the JMAG seats in use: ONE per solve. The solver kernel family as the
#: installation ships it (motronics ``hamilton/adapters/jmag/processes.py``, checked 2026-09-19 against
#: JMAG-Designer25.1). Not ``execsolver.exe`` -- it launches ``jam.exe``, so counting both counts one solve
#: twice -- and not ``scheduler.exe`` or ``designer.exe``: a seat is a SOLVE, never an open Designer (user
#: correction 2026-10-16).
JMAG_SOLVER_IMAGES: Final = ('jam.exe', 'jam_c.exe', 'jam_intel_mpi_b.exe', 'jam_intel_mpi_c.exe')

_REMEDIES: Final = {
    'uv': 'install uv: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"',
    'git': 'install Git for Windows: winget install --id Git.Git -e',
    'node': 'install Node.js LTS: winget install --id OpenJS.NodeJS.LTS -e',
    'codex': 'install the Codex CLI: npm install -g @openai/codex',
}
_JMAG_REMEDY: Final = 'install JMAG-Designer; its installer registers ' + ' and '.join(JMAG_PROGIDS)
_CREDENTIAL_REMEDY: Final = (
    'store your OWN git credential for the forge once -- `git clone <forge>/<repo>.git` anywhere and sign '
    'in, or `python -m dev_lab.dev.forge auth login` -- then re-run'
)
#: Prompting off: only a STORED credential can answer.
_NO_PROMPT: Final = {'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'}


def com_server(progid: str) -> Path | None:
    """The executable COM *progid* is registered to (``HKCR`` -> ``LocalServer32``), when it exists on disk."""
    if sys.platform != 'win32':
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f'{progid}\\CLSID') as key:
            clsid = winreg.QueryValue(key, None)
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f'CLSID\\{clsid}\\LocalServer32') as key:
            server = winreg.QueryValue(key, None).strip()
    except OSError:
        return None
    exe = Path(server[1:].split('"', 1)[0] if server.startswith('"') else server.split(' ', 1)[0])
    return exe if exe.is_file() else None


def _own_python(checkout: Path) -> tuple[str, ...]:
    return (str(venv_python(checkout)),)


#: The machine-file table naming the synced workstation registry: ``[workstation] registry = "<hosts.json>"``.
REGISTRY_TABLE: Final = 'workstation'
#: The registry role that makes a workstation a ``forge serve`` host (user ruling 2026-10-22: G alone).
FORGE_ROLE: Final = 'forge'


class NoRegistry(ValueError):
    """No workstation registry is declared here, so whether this machine serves the forge is undeclared."""


def _computer() -> str:
    return os.environ.get('COMPUTERNAME') or socket.gethostname()


def forge_refusal(computer: str) -> str | None:
    """``None`` when the registry gives *computer* the ``forge`` role; else why it may not serve.

    ONE PLACE says which workstation serves the forge: the synced registry's ``roles``. This machine's entry
    is the one whose ``computer`` (the OS name, ``COMPUTERNAME``) equals *computer*, case-insensitively, else
    the one whose ``name`` does -- ``computer`` first because it is read off the machine, ``name`` a label.
    No ``[workstation] registry`` raises :class:`NoRegistry`: a workstation never serves by omission.
    """
    declared = section(REGISTRY_TABLE).get('registry')
    if not isinstance(declared, str) or not declared:
        msg = (
            f'no [{REGISTRY_TABLE}] registry in {config_path()}: declare the synced hosts.json there; '
            f'only a host whose entry carries role "{FORGE_ROLE}" serves the forge'
        )
        raise NoRegistry(msg)
    registry = Path(declared).expanduser()
    try:
        hosts = json.loads(registry.read_text(encoding='utf-8-sig'))['hosts']
    except (OSError, ValueError, KeyError, TypeError) as bad:
        return f'registry {registry} unreadable ({bad}); not serving until it reads'
    key = computer.casefold()
    entry = next((h for h in hosts if str(h.get('computer', '')).casefold() == key), None) or next(
        (h for h in hosts if str(h.get('name', '')).casefold() == key), None
    )
    if entry is None:
        return f'no entry for computer {computer!r} in {registry}; add one with role "{FORGE_ROLE}" to serve'
    roles = list(entry.get('roles') or [])
    if FORGE_ROLE in roles:
        return None
    return f'{registry} roles of {entry.get("name")}: {roles}; add "{FORGE_ROLE}" to serve'


def _release(checkout: Path) -> list[str]:
    """Release every run a dead serve left journaled in *checkout* -- the forge serve's own re-attach path."""
    if not journaled(checkout):  # nothing to release: no forge client is built
        return []
    return reattach(checkout, client_for(checkout), lease=DEFAULT_LEASE, say=emit)


@dataclass(frozen=True)
class Programs:
    """Every program and probe the deploy uses; a test swaps in fakes."""

    git: tuple[str, ...] = ('git',)
    schtasks: tuple[str, ...] = ('schtasks',)
    bootstrap: tuple[str, ...] = (sys.executable, '-m', 'dev_lab.dev.dep', '--bootstrap')
    python_of: Callable[[Path], tuple[str, ...]] = field(default=_own_python)
    which: Callable[[str], str | None] = shutil.which
    com: Callable[[str], Path | None] = com_server
    windows: bool = os.name == 'nt'
    home: Path = field(default_factory=servetask.home)
    alarm: Callable[[Alarm], object] = sound
    computer: str = field(default_factory=_computer)
    release: Callable[[Path], list[str]] = _release


def _capabilities(text: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in filter(None, (part.strip() for part in text.split(','))):
        name, _, seats = item.partition(':')
        if seats and not seats.isdigit():
            msg = f'--capabilities {item!r}: expected <name> or <name>:<seats>'
            raise argparse.ArgumentTypeError(msg)
        out[name] = {'seats': int(seats)} if seats else {}
        if name == 'jmag':
            out[name]['in_use'] = {'process': list(JMAG_SOLVER_IMAGES)}
    try:
        return provided(out)
    except ValueError as bad:
        raise argparse.ArgumentTypeError(str(bad)) from None


def _seat_margin(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in filter(None, (part.strip() for part in text.split(','))):
        name, sep, count = item.partition('=')
        if not sep or not count.isdigit():
            msg = f'--seat-margin {item!r}: expected <name>=<seats kept>'
            raise argparse.ArgumentTypeError(msg)
        out[name] = int(count)
    return out


def _reserve(args: argparse.Namespace) -> dict[str, Any]:
    """The ``[reserve]`` keys this deploy was given; a seat margin for a capability not declared is refused."""
    if stray := sorted(set(args.seat_margin) - set(args.capabilities)):
        msg = f'--seat-margin names {", ".join(stray)}, not declared in --capabilities'
        raise ValueError(msg)
    given = {'cpu_margin': args.cpu_margin, 'mem_margin': args.mem_margin, 'seat_margin': args.seat_margin or None}
    return {key: value for key, value in given.items() if value is not None}


def _repos(text: str) -> tuple[str, ...]:
    repos = tuple(dict.fromkeys(part.strip() for part in text.split(',') if part.strip()))
    if KIT not in repos:
        msg = f'the Task runs from the {KIT} checkout, so --repos must include it'
        raise argparse.ArgumentTypeError(msg)
    return repos


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.workstation', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    dep = verbs.add_parser('deploy', help='make this workstation a forge serve host')
    dep.add_argument('--repos', type=_repos, required=True, help=f'comma-separated; must include {KIT}')
    dep.add_argument('--capabilities', type=_capabilities, default={}, help='comma-separated name or name:seats')
    dep.add_argument('--cpu-margin', type=float, help='[reserve] cores the forge never takes (default 1)')
    dep.add_argument('--mem-margin', type=float, help='[reserve] memory fraction the forge never takes (default 0.1)')
    dep.add_argument('--seat-margin', type=_seat_margin, default={}, help='[reserve] seats never lent: name=N,...')
    dep.add_argument('--forge', default='', help='https base a missing checkout is cloned from: <forge>/<repo>.git')
    dep.add_argument('--root', type=Path, default=Path.home() / 'src', help='checkouts live in <root>/<repo>')
    dep.add_argument('--ref', default='integrate/main', help='the branch a new clone follows')
    dep.add_argument('--dry-run', action='store_true', help='print every action; change nothing')
    verbs.add_parser('serve', help="the Task's action: serve every [serve] repo under one lock")
    return parser


def _probe(programs: Programs, capabilities: Mapping[str, Any]) -> list[str]:
    wanted = ['uv', 'git', *(_WORKSTATION_KIT if WORKSTATION in capabilities else ())]
    emit(f'[probe] {", ".join([*wanted, *(["jmag"] if "jmag" in capabilities else [])])}')
    missing = [f'{tool} not on PATH: {_REMEDIES[tool]}' for tool in wanted if programs.which(tool) is None]
    if 'jmag' in capabilities and (absent := [p for p in JMAG_PROGIDS if programs.com(p) is None]):
        missing.append(f'COM class {", ".join(absent)} not registered: {_JMAG_REMEDY}')
    return missing


def _url(programs: Programs, checkout: Path, name: str, forge: str) -> str:
    if (checkout / '.git').exists():
        return read([*programs.git, '-C', str(checkout), 'remote', 'get-url', 'origin']).stdout.strip()
    return f'{forge.rstrip("/")}/{name}.git' if forge else ''


def _credentials(programs: Programs, urls: Mapping[str, str]) -> list[str]:
    emit('[credential] git ls-remote per repo, prompting off: only a stored credential answers')
    denied = []
    for name, url in urls.items():
        argv = [*programs.git, '-c', 'credential.interactive=never', 'ls-remote', '-q', url, 'HEAD']
        rc = run_network_verb(argv, env={**os.environ, **_NO_PROMPT}).returncode
        emit(f'  {name}: {"ok" if rc == 0 else f"refused (exit {rc})"}')
        if rc:
            denied.append(name)
    return denied


def _checkout(step: Step, programs: Programs, checkout: Path, *, url: str, ref: str) -> Moved:
    if not (checkout / '.git').exists():
        what = f'{checkout.name}: git clone -b {ref} {url} {checkout}'
        clone = [*programs.git, 'clone', '-q', '-b', ref, url, str(checkout)]
        return Moved(step.change(what, [])) if step.dry else network(step, what, clone)
    return follow(step, programs.git, checkout)


def _hooks(step: Step, programs: Programs, checkout: Path, name: str) -> int:
    if step.dry and not venv_python(checkout).is_file():
        return step.change(f'{name}: hook_install --install, when its hooks are not live', [])
    hook = [*programs.python_of(checkout), '-m', 'dev_lab.dev.hook_install', '--repo', str(checkout)]
    rc = read(hook).returncode
    if rc in {0, 2}:
        emit(f'  {name}: ' + ('hooks live' if rc == 0 else 'declares no hook'))
        return 0
    return step.change(f'{name}: hook_install --install', [*hook, '--install'], cwd=checkout)


def _machine_file(step: Step, tables: Mapping[str, Mapping[str, Any]]) -> int:
    path = config_path()
    emit(f'[machine file] {path}')
    before = path.read_text(encoding='utf-8') if path.is_file() else ''
    try:
        after = merged(before, tables)
    except ValueError as broken:
        emit(f'deploy refused: {path}: {broken}', err=True)
        return 2
    if after == before:
        emit('  already declares every table')
        return 0
    for line in diff(before, after, str(path)).splitlines():
        emit(f'  {line}')
    if step.dry:
        emit('  [dry-run] the diff above is not written')
        return 0
    durable_text(path, after)
    return 0


def _task(step: Step, programs: Programs, lab: Path) -> int:
    emit(f'[task] {servetask.TASK}')
    want = servetask.definition_of(lab)
    query = read([*programs.schtasks, *servetask.query_argv()[1:]])
    if query.returncode == 0 and servetask.installed(query.stdout) == want:
        emit(f'  in place: {want.command} {want.arguments}')
        rc = 0
    else:
        xml = programs.home / f'{servetask.TASK}.xml'
        if not step.dry:
            xml.parent.mkdir(parents=True, exist_ok=True)
            xml.write_text(servetask.task_xml(want, user=servetask.this_user()), encoding='utf-16')
        command = servetask.create_argv(xml)
        rc = step.change(subprocess.list2cmdline(command), [*programs.schtasks, *command[1:]])
    emit(f'  stop: {servetask.DISABLE}')
    return rc


def _preflight(args: argparse.Namespace, tools: Programs, checkouts: Mapping[str, Path]) -> dict[str, str] | str:
    """Every read-only refusal before anything changes; the clone url of each repo when none applies."""
    if not tools.windows:
        return 'a workstation serves from a Windows Scheduled Task; a POSIX host serves from cron'
    if why := forge_refusal(tools.computer):
        return f'not a forge host: {why}'
    if missing := _probe(tools, args.capabilities):
        for line in missing:
            emit(f'  {line}', err=True)
        return f'{len(missing)} missing; install each as named, then re-run'
    urls = {name: _url(tools, co, name, args.forge) for name, co in checkouts.items()}
    if unknown := [name for name, url in urls.items() if not url]:
        return f'no checkout of {", ".join(unknown)} under {args.root}; pass --forge <https base> to clone'
    if denied := _credentials(tools, urls):
        return f'no stored git credential reads {", ".join(denied)}; {_CREDENTIAL_REMEDY}'
    return urls


def _checkouts(
    step: Step, tools: Programs, checkouts: Mapping[str, Path], urls: Mapping[str, str], ref: str
) -> dict[str, str]:
    """Clone or fast-forward each checkout, then bootstrap its venv and install its hooks where needed.

    A repo whose step fails is refused ALONE: skipped by every later step and returned by name with its
    reason -- one repo's outdated state never stops the others.
    """
    emit('[checkouts] clone, or fast-forward a clean checkout')
    done = {name: _checkout(step, tools, co, url=urls[name], ref=ref) for name, co in checkouts.items()}
    refused = {name: one.why or f'checkout exited {one.rc}' for name, one in done.items() if one.rc}
    emit('[venvs] -m dev_lab.dev.dep --bootstrap where missing or moved')
    for name, co in checkouts.items():
        if name not in refused and (rc := sync_venv(step, tools.bootstrap, co)):
            refused[name] = f'its venv bootstrap exited {rc}'
    emit('[hooks] hook_install --install where not live')
    for name, co in checkouts.items():
        if name not in refused and (rc := _hooks(step, tools, co, name)):
            refused[name] = f'its hook install exited {rc}'
    return refused


def deploy(argv: Sequence[str], *, programs: Programs | None = None) -> int:
    """Run the deployment *argv* asks for; 0 done, 2 refused (the message names the remedy)."""
    parser = _parser()
    args = parser.parse_args(['deploy', *argv])
    try:
        reserve = _reserve(args)
    except ValueError as bad:
        parser.error(str(bad))
    tools = programs or Programs()
    args.root = args.root.expanduser().absolute()
    checkouts = {name: args.root / name for name in args.repos}
    try:
        urls = _preflight(args, tools, checkouts)
    except ValueError as bad:
        urls = str(bad)
    if isinstance(urls, str):
        emit(f'deploy refused: {urls}', err=True)
        return 2
    step = Step(Tools(git=tools.git), dry=args.dry_run)
    refused = _checkouts(step, tools, checkouts, urls, args.ref)
    tables: dict[str, dict[str, Any]] = {f'capabilities.{name}': facts for name, facts in args.capabilities.items()}
    if reserve:
        tables['reserve'] = reserve
    tables['serve'] = {'repos': [name for name in args.repos if name not in refused], 'root': str(args.root)}
    rc = _machine_file(step, tables) or _task(step, tools, checkouts[KIT])
    for name, why in refused.items():
        tools.alarm(Alarm(RUN, urls[name], f'workstation deploy refused {name}; this box does not serve it', why))
        emit(f'deploy refused {name} (left out of [serve] repos): {why}', err=True)
    return rc or (2 if refused else 0)


def _stand_down(tools: Programs, root: Path, repos: Sequence[str], why: str) -> int:
    """A host without the ``forge`` role claims nothing; a run a dead serve journaled is released, never abandoned."""
    emit(f'[serve] not a forge host ({why})', flush=True)
    for name in repos:
        for line in tools.release(root / name):
            emit(f'[serve] {name} {line}')
    return 0


def serve(
    *,
    run: Callable[..., Any] = _door.run,
    lock: Path | None = None,
    out: IO[str] | None = None,
    programs: Programs | None = None,
) -> int:
    """Refresh, then ``forge serve``, each ``[serve] repos`` checkout under one lock; the worst exit.

    dev-lab is refreshed first, then each repo in order (:func:`dev_lab.dev.hostrefresh.refresh`):
    a repo whose refresh fails is RELEASED this tick, its reason named in the serve log, and never stops the next one.
    The serving dev-lab checkout's own hooks are re-installed whenever they are not live (stale after a move).
    Every child starts with no console window; *out*, when given, receives its stdout and stderr.
    """
    table = section('serve')
    repos, root = table.get('repos'), table.get('root')
    if not (isinstance(repos, list) and repos and isinstance(root, str)):
        emit(f'[serve] refused: no [serve] repos and root in {config_path()}; run `workstation deploy`', err=True)
        return 2
    tools = programs or Programs()
    try:
        why = forge_refusal(tools.computer)
    except NoRegistry as undeclared:
        emit(f'[serve] refused: {undeclared}', err=True)
        return 2
    step = Step(Tools(git=tools.git), dry=False)
    with held(lock or default_lock()) as mine:
        if not mine:
            emit('[serve] another forge serve holds the lock; this one does nothing', err=True)
            return 0
        if why:
            return _stand_down(tools, Path(root), repos, why)
        worst = 0
        for name in sorted(repos, key=lambda repo: repo != KIT):
            checkout = Path(root) / name
            emit(f'[serve] {name}', flush=True)
            if why := refresh(step, git=tools.git, bootstrap=tools.bootstrap, checkout=checkout):
                emit(f'[serve] {name} released, not served this tick: {why}', err=True)
                worst = max(worst, 2)
                continue
            # the serving kit's own shims follow it (plan R1): kept current by the machine, never by hand
            if name == KIT and (rc := _hooks(step, tools, checkout, name)):
                emit(f'[serve] {name}: its hooks were not re-installed (exit {rc}); the old shims stay', err=True)
            streams = {'stdin': subprocess.DEVNULL, 'stdout': out, 'stderr': subprocess.STDOUT} if out else {}
            rc = run(host_serve_argv(), cwd=checkout, check=False, **streams).returncode
            if rc:
                emit(f'[serve] {name} exited {rc}', err=True)
            worst = max(worst, rc)
    return worst


def main(argv: Sequence[str] | None = None) -> int:
    """``deploy ...`` or ``serve``; a retired spelling is refused by name with its remedy."""
    args = list(sys.argv[1:] if argv is None else argv)
    if refused := next(filter(None, (refusal('workstation', word.split('=', 1)[0]) for word in args)), None):
        emit(refused, err=True)
        return 2
    if args[:1] == ['deploy']:
        return deploy(args[1:])
    _parser().parse_args(args)
    if sys.stdout is not None:
        return serve()
    with servetask.open_log(servetask.log_path()) as log:  # pythonw: no console, so no streams
        sys.stdout = sys.stderr = log
        try:
            return serve(out=log)
        finally:
            sys.stdout = sys.stderr = None


if __name__ == '__main__':
    sys.exit(main())
