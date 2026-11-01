"""A WINDOWS WORKSTATION AS A ``forge serve`` HOST, in one run: ``python -m dev_lab.dev.workstation deploy``.

The counterpart of a cluster account's ``python -m dev_lab.dev.hpchost deploy``, and it reuses that
deploy's run-or-print :class:`~dev_lab.dev.hpchost.steps.Step`.

``deploy --repos <repo>,... (--capabilities workstation,jmag:4 | --role light) [--forge <https base>]
[--ref BRANCH] [--dry-run]``, each step reporting and safe to repeat. A ``--role`` is a declared profile
(:data:`ROLES`: its capabilities and ``[serve]`` rule); ``template --role <role> --repos ...`` prints the tables
it writes. The ``light`` role withholds every :data:`HEAVY` tool and refuses one in ``--capabilities``.
Nothing is reserved for the person at the box (user ruling 2026-10-25): they DECLARE their use as a ledger
claim (``python -m lab_commons.box claim``).

1. PROBE: ``uv`` and ``git`` on PATH; ``node`` and ``codex`` when ``workstation`` is declared; JMAG Designer and
   its Scheduler COM classes when ``jmag`` is. Every missing item is refused at once, each with its remedy.
2. CREDENTIAL: ``git ls-remote`` of every repo with prompting off, so only a STORED git credential
   answers; none is ever read or printed. A refusal names the one manual step.
3. CHECKOUTS at ``<forge home>/repos/<repo>`` (:func:`dev_lab.dev.servetask.checkout`), derived from the
   platform data dir and never configured (user ruling 2026-10-26: serve checkouts are neither user-visible
   nor shared with dev checkouts): clone ``<forge>/<repo>.git`` at ``--ref``, or fast-forward an existing
   CLEAN checkout to its upstream; a dirty one is refused.
4. VENVS: ``-m dev_lab.dev.dep --bootstrap <checkout>`` when the venv is missing or its ``pyproject.toml``
   or ``uv.lock`` changed since its last sync (a stamp in the venv, written only after a sync succeeds).
5. HOOKS: ``-m dev_lab.dev.hook_install --install`` in each checkout whose hooks are not live.
6. MACHINE FILE (:mod:`lab_commons.config`): ``[capabilities.<name>]`` (``seats`` from ``name:N``; a ``jmag``
   row also ``in_use = { process = JMAG_SOLVER_IMAGES }``, so a solve a person starts is a seat taken) and
   ``[serve] repos`` (with a role, also ``parts`` and ``withhold``) merged in place. A retired ``[serve] root``
   and every RETIRED ``[capabilities.<name>]`` table are removed -- one retired into ``[runtimes.<name>]`` has
   its keys carried there; every other table, key and comment is kept, and ``--dry-run`` prints the diff.
7. TASK: the one ``lab-forge-serve`` Scheduled Task (:mod:`dev_lab.dev.servetask`), its action derived from
   the forge home alone (the dev-lab serve checkout's ``pythonw``), registered from its XML definition and
   rewritten only when the installed one reads back different.

``--dry-run`` reads but changes nothing. A second run changes nothing.

A REFUSAL IN STEPS 3-5 BELONGS TO ITS REPO (incident 2026-10-13, the cluster deploy's twin): the repo is
reported with its reason, skipped by the later steps and left out of ``[serve] repos`` so the Task never
serves it; the deploy finishes for the others, raises one forge ``run`` alarm per refused repo
(:mod:`dev_lab.dev.forgealarm`), and exits 2 naming each.

``serve`` IS THE TASK'S ACTION, and refuses (exit 2) to run from any interpreter outside the dev-lab serve
checkout: a dev checkout's venv is never the kit (incident 2026-10-26). So the KIT'S OWN venv is resynced by
the dev-lab refresh that runs first whenever its ``pyproject.toml``/``uv.lock`` moved, before any lane serves.
Under the per-user serve lock (:mod:`dev_lab.dev.servelock`),
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
from lab_commons.compute.serves import SERVE_TABLE
from lab_commons.config import config_path, section
from lab_commons.hpc.retired import refusal
from lab_commons.log import emit

from dev_lab.dev import servetask
from dev_lab.dev.forgealarm import RUN, Alarm, sound
from dev_lab.dev.forgeclaim import DEFAULT_LEASE
from dev_lab.dev.forgeintent import journaled, reattach
from dev_lab.dev.forgework import client_for
from dev_lab.dev.hostrefresh import ENV_STAMP, Moved, follow, network, read, refresh, sync_venv, venv_python
from dev_lab.dev.hpchost.spec import KIT
from dev_lab.dev.hpchost.steps import Step, Tools
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.servelanes import serve_lanes, serving
from dev_lab.dev.servelock import default_lock, forge_home, held
from dev_lab.dev.workstationfile import (
    ROLES,
    WORKSTATION,
    capabilities,
    machine_file,
    role_refusal,
    role_tables,
    template,
)

if sys.platform == 'win32':
    import winreg

__all__ = [
    'FORGE_ROLE',
    'JMAG_PROGIDS',
    'REGISTRY_TABLE',
    'NoRegistry',
    'Programs',
    'com_server',
    'deploy',
    'forge_refusal',
    'main',
    'serve',
]

#: What a ``workstation`` declaration promises on ``PATH`` -- probed at deploy, so the declaration cannot lie.
_WORKSTATION_KIT: Final = ('node', 'codex')

#: The COM classes a ``jmag`` host drives: the Designer and its Scheduler.
JMAG_PROGIDS: Final = ('designer.Application', 'scheduler.JobApplication')


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
    home: Path = field(default_factory=forge_home)  # the forge's machine home; serve checkouts in <home>/repos
    executable: Path = Path(sys.executable)  # the interpreter serving; it must be the dev-lab serve checkout's
    alarm: Callable[[Alarm], object] = sound
    computer: str = field(default_factory=_computer)
    release: Callable[[Path], list[str]] = _release


def _repos(text: str) -> tuple[str, ...]:
    repos = tuple(dict.fromkeys(part.strip() for part in text.split(',') if part.strip()))
    if not repos:
        msg = 'name at least one repo to serve'
        raise argparse.ArgumentTypeError(msg)
    return repos


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.workstation', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    dep = verbs.add_parser('deploy', help='make this workstation a forge serve host')
    dep.add_argument(
        '--repos',
        type=_repos,
        required=True,
        help=f'comma-separated, the repos served; {KIT} only if its queue is served here',
    )
    dep.add_argument('--capabilities', type=capabilities, default=None, help='comma-separated name or name:seats')
    dep.add_argument(
        '--role', choices=sorted(ROLES), help='a declared profile (ROLES): its capabilities and [serve] rule'
    )
    dep.add_argument('--forge', default='', help='https base a missing checkout is cloned from: <forge>/<repo>.git')
    dep.add_argument('--ref', default='integrate/main', help='the branch a new clone follows')
    dep.add_argument('--dry-run', action='store_true', help='print every action; change nothing')
    verbs.add_parser('serve', help="the Task's action: serve every [serve] repo under one lock")
    tpl = verbs.add_parser('template', help='print the machine-file tables a --role deploy writes')
    tpl.add_argument('--role', choices=sorted(ROLES), required=True)
    tpl.add_argument(
        '--repos',
        type=_repos,
        required=True,
        help=f'comma-separated, the repos served; {KIT} only if its queue is served here',
    )
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


def _task(step: Step, programs: Programs) -> int:
    emit(f'[task] {servetask.TASK}')
    want = servetask.definition_of(programs.home)
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
        return f'no checkout of {", ".join(unknown)} in {servetask.repos(tools.home)}; pass --forge <https base>'
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
    if args.capabilities is None:
        args.capabilities = capabilities(','.join(ROLES[args.role].capabilities)) if args.role else {}
    if args.role and (why := role_refusal(args.role, args.capabilities)):
        parser.error(why)
    tools = programs or Programs()
    # the Task runs from the kit checkout, so it is deployed on every host, served or not (ruling 2026-10-29)
    checkouts = {name: servetask.checkout(tools.home, name) for name in dict.fromkeys((KIT, *args.repos))}
    try:
        urls = _preflight(args, tools, checkouts)
    except ValueError as bad:
        urls = str(bad)
    if isinstance(urls, str):
        emit(f'deploy refused: {urls}', err=True)
        return 2
    step = Step(Tools(git=tools.git), dry=args.dry_run)
    refused = _checkouts(step, tools, checkouts, urls, args.ref)
    served = [name for name in args.repos if name not in refused]
    if args.role:
        tables = role_tables(ROLES[args.role], args.capabilities, served)
    else:
        tables = {f'capabilities.{name}': dict(facts) for name, facts in args.capabilities.items()}
        tables[SERVE_TABLE] = {'repos': served}
    tables[SERVE_TABLE].update(dict.fromkeys(servetask.RETIRED_SERVE_KEYS))  # a retired key merged as None is removed
    rc = machine_file(step, tables) or _task(step, tools)
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


def _kit_at(git: Sequence[str], kit: Path) -> tuple[str, str]:
    """What the kit's code is: its HEAD and the env key its venv was last synced at."""
    stamp = kit / '.venv' / ENV_STAMP
    head = read([*git, '-C', str(kit), 'rev-parse', 'HEAD']).stdout.strip()
    return head, stamp.read_text(encoding='utf-8') if stamp.is_file() else ''


def _skipping(done: str, refresh: Callable[[str], int]) -> Callable[[str], int]:
    """*refresh* for every lane but *done*, which this tick has already refreshed."""
    return lambda name: 0 if name == done else refresh(name)


def serve(
    *,
    run: Callable[..., Any] = _door.run,
    lock: Path | None = None,
    out: IO[str] | None = None,
    programs: Programs | None = None,
    period_s: float | None = None,
) -> int:
    """Refresh, then ``forge serve``, each ``[serve] repos`` checkout under one lock, each in a LANE; the worst exit.

    The kit (dev-lab) is refreshed first whether or not ``[serve] repos`` names it (ruling 2026-10-29), then
    each repo in order (:func:`dev_lab.dev.hostrefresh.refresh`):
    a repo whose refresh fails is RELEASED this tick, its reason named in the serve log, and never stops the next one.
    The serving dev-lab checkout's own hooks are re-installed whenever they are not live (stale after a move).

    ONE BUSY REPO NEVER STARVES THE OTHERS (incident 2026-10-25: a downstream part held the one host lock for
    an hour, and dev-lab's card read STALE with its whole queue unclaimed). Each repo serves in a lane of its
    own; a lane whose serve ended serves again *period_s* later (the ``[schedule] tick_minutes``) while any
    other lane's serve still runs, so its card keeps ticking and its queue keeps being claimed against the
    one box ledger. dev-lab is never refreshed again inside one call: the other lanes run its code.

    A MOVED KIT ENDS THE TICK (incident 2026-10-30: G served a day on a kit that still gated merges on a
    retired parts PASS). The kit is refreshed before any lane; when its HEAD or venv moved, this process is
    the OLD code, so it serves nothing and exits 0 -- the Task's next run starts on the new kit. A kit that
    cannot refresh (a dirty checkout is never touched) sounds a ``run`` alarm naming it; the others serve.
    Every child starts with no console window; *out*, when given, receives its stdout and stderr.
    """
    table, tools = section('serve'), programs or Programs()
    if refused := servetask.serve_refusal(table, tools.executable, tools.home):
        emit(f'[serve] refused: {refused}', err=True)
        return 2
    repos, root = table['repos'], servetask.repos(tools.home)
    try:
        why = forge_refusal(tools.computer)
    except NoRegistry as undeclared:
        emit(f'[serve] refused: {undeclared}', err=True)
        return 2
    step = Step(Tools(git=tools.git), dry=False)

    def refreshed(name: str) -> int:
        checkout = servetask.checkout(tools.home, name)
        emit(f'[serve] {name}', flush=True)
        if why := refresh(step, git=tools.git, bootstrap=tools.bootstrap, checkout=checkout):
            emit(f'[serve] {name} released, not served this tick: {why}', err=True)
            if name == KIT:
                url = read([*tools.git, '-C', str(checkout), 'remote', 'get-url', 'origin']).stdout.strip()
                tools.alarm(Alarm(RUN, url, f'serve kit {checkout} cannot refresh; this host runs an old kit', why))
            return 2
        # the serving kit's own shims follow it (plan R1): kept current by the machine, never by hand
        if name == KIT and (rc := _hooks(step, tools, checkout, name)):
            emit(f'[serve] {name}: its hooks were not re-installed (exit {rc}); the old shims stay', err=True)
        return 0

    with held(lock or default_lock()) as mine:
        if not mine:
            emit('[serve] another forge serve holds the lock; this one does nothing', err=True)
            return 0
        if why:
            return _stand_down(tools, root, repos, why)
        # the kit is refreshed every tick, served or not (ruling 2026-10-29), and before any lane
        kit = servetask.checkout(tools.home, KIT)
        before = _kit_at(tools.git, kit)
        kit_rc = refreshed(KIT)
        if _kit_at(tools.git, kit) != before:
            emit(f'[serve] {KIT} moved; this process is the old kit, so the next Task run serves', flush=True)
            return kit_rc
        lanes = [name for name in repos if not (name == KIT and kit_rc)]
        return max(kit_rc, serve_lanes(lanes, _skipping(KIT, refreshed), serving(root, run, out), period_s=period_s))


def main(argv: Sequence[str] | None = None) -> int:
    """``deploy ...`` or ``serve``; a retired spelling is refused by name with its remedy."""
    args = list(sys.argv[1:] if argv is None else argv)
    words = (word.split('=', 1)[0] for word in args)
    if refused := next(filter(None, (refusal('workstation', w) or servetask.retired_flag(w) for w in words)), None):
        emit(refused, err=True)
        return 2
    if args[:1] == ['deploy']:
        return deploy(args[1:])
    parsed = _parser().parse_args(args)
    if parsed.verb == 'template':
        emit(template(parsed.role, parsed.repos).rstrip())
        return 0
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
