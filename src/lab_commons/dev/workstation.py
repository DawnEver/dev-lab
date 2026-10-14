"""A WINDOWS WORKSTATION AS A ``forge serve`` HOST, in one run: ``python -m lab_commons.dev.workstation deploy``.

The counterpart of a cluster account's ``python -m lab_commons.hpc deploy``. It lives here, not in
:mod:`lab_commons.hpc`, because what it schedules is this package's own serve and lock (hpc imports no
dev code); it reuses hpc's run-or-print :class:`~lab_commons.hpc.deploy_steps.Step`.

``deploy --repos lab-commons,<repo>,... --capabilities dev_checkout,node,jmag:4 [--forge <https base>]
[--root DIR] [--ref BRANCH] [--delegates LOGIN,...] [--dry-run]``, each step reporting and safe to repeat:

1. PROBE: ``uv`` and ``git`` on PATH; ``node`` when the ``node`` capability is declared; JMAG Designer and
   its Scheduler COM classes when ``jmag`` is. Every missing item is refused at once, each with its remedy.
2. CREDENTIAL: ``git ls-remote`` of every repo with prompting off, so only a STORED git credential
   answers; none is ever read or printed. A refusal names the one manual step.
3. CHECKOUTS under ``--root`` (default ``~/src``): clone ``<forge>/<repo>.git`` at ``--ref``,
   or fast-forward an existing CLEAN checkout to its upstream; a dirty one is refused.
4. VENVS: ``-m lab_commons.dev.dep --bootstrap <checkout>`` when the venv is missing or the checkout moved.
5. HOOKS: ``-m lab_commons.dev.hook_install --install`` in each checkout whose hooks are not live.
6. MACHINE FILE (:mod:`lab_commons.config`): ``[capabilities.<name>]`` (``seats`` from ``name:N``) and
   ``[serve] repos, root`` and ``[reserve] delegates`` (the logins this box's user lets reserve it,
   :mod:`lab_commons.compute.ledger`) merged in place; every other table, key and comment is kept,
   and ``--dry-run`` prints the diff.
7. TASK: the one ``lab-forge-serve`` Scheduled Task (:mod:`lab_commons.dev.servetask`), registered from
   its XML definition and rewritten only when the installed one reads back different.

``--dry-run`` reads but changes nothing. A second run changes nothing.

A REFUSAL IN STEPS 3-5 BELONGS TO ITS REPO (incident 2026-10-13, the cluster deploy's twin): the repo is
reported with its reason, skipped by the later steps and left out of ``[serve] repos`` so the Task never
serves it; the deploy finishes for the others, raises one forge ``run`` alarm per refused repo
(:mod:`lab_commons.dev.forgealarm`), and exits 2 naming each.

``serve`` IS THE TASK'S ACTION: under the per-user serve lock (:mod:`lab_commons.dev.servelock`),
``forge serve`` once per ``[serve] repos`` entry, in order, each in its own checkout and venv.
Its exit is the worst child's; one repo's failure never skips the next. Each child starts with no
console window; under ``pythonw`` (no streams at all) the serve and its children write to the capped
serve log (:func:`lab_commons.dev.servetask.open_log`).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Final

from lab_commons.box.machine import provided
from lab_commons.config import config_path, section
from lab_commons.dev import servetask
from lab_commons.dev._machinefile import diff, merged
from lab_commons.dev.forgealarm import RUN, Alarm, sound
from lab_commons.dev.servelock import default_lock, held
from lab_commons.dev.venvpath import venv_interpreter
from lab_commons.hpc.deploy_spec import LAB_COMMONS
from lab_commons.hpc.deploy_steps import Step, Tools
from lab_commons.hpc.retired import refusal
from lab_commons.log import emit

if sys.platform == 'win32':
    import winreg

__all__ = ['JMAG_PROGIDS', 'Programs', 'com_server', 'deploy', 'main', 'serve']

#: The COM classes a ``jmag`` host drives: the Designer and its Scheduler.
JMAG_PROGIDS: Final = ('designer.Application', 'scheduler.JobApplication')

_REMEDIES: Final = {
    'uv': 'install uv: powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"',
    'git': 'install Git for Windows: winget install --id Git.Git -e',
    'node': 'install Node.js LTS: winget install --id OpenJS.NodeJS.LTS -e',
}
_JMAG_REMEDY: Final = 'install JMAG-Designer; its installer registers ' + ' and '.join(JMAG_PROGIDS)
_CREDENTIAL_REMEDY: Final = (
    'store your OWN git credential for the forge once -- `git clone <forge>/<repo>.git` anywhere and sign '
    'in, or `python -m lab_commons.dev.forge auth login` -- then re-run'
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


def _venv_python(checkout: Path) -> Path:
    return checkout / venv_interpreter(os_name=os.name)


def _own_python(checkout: Path) -> tuple[str, ...]:
    return (str(_venv_python(checkout)),)


@dataclass(frozen=True)
class Programs:
    """Every program and probe the deploy uses; a test swaps in fakes."""

    git: tuple[str, ...] = ('git',)
    schtasks: tuple[str, ...] = ('schtasks',)
    bootstrap: tuple[str, ...] = (sys.executable, '-m', 'lab_commons.dev.dep', '--bootstrap')
    python_of: Callable[[Path], tuple[str, ...]] = field(default=_own_python)
    which: Callable[[str], str | None] = shutil.which
    com: Callable[[str], Path | None] = com_server
    windows: bool = os.name == 'nt'
    home: Path = field(default_factory=servetask.home)
    alarm: Callable[[Alarm], object] = sound


def _read(argv: Sequence[str], env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """A READ-ONLY call, also under ``--dry-run``; its output is never echoed."""
    return subprocess.run(
        argv, capture_output=True, text=True, encoding='utf-8', errors='replace', check=False,
        stdin=subprocess.DEVNULL, env={**os.environ, **(env or {})},
    )  # fmt: skip


def _capabilities(text: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in filter(None, (part.strip() for part in text.split(','))):
        name, _, seats = item.partition(':')
        if seats and not seats.isdigit():
            msg = f'--capabilities {item!r}: expected <name> or <name>:<seats>'
            raise argparse.ArgumentTypeError(msg)
        out[name] = {'seats': int(seats)} if seats else {}
    try:
        return provided(out)
    except ValueError as bad:
        raise argparse.ArgumentTypeError(str(bad)) from None


def _repos(text: str) -> tuple[str, ...]:
    repos = tuple(dict.fromkeys(part.strip() for part in text.split(',') if part.strip()))
    if LAB_COMMONS not in repos:
        msg = f'the Task runs from the {LAB_COMMONS} checkout, so --repos must include it'
        raise argparse.ArgumentTypeError(msg)
    return repos


def _logins(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(part.strip() for part in text.split(',') if part.strip()))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m lab_commons.dev.workstation', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    dep = verbs.add_parser('deploy', help='make this workstation a forge serve host')
    dep.add_argument('--repos', type=_repos, required=True, help=f'comma-separated; must include {LAB_COMMONS}')
    dep.add_argument('--capabilities', type=_capabilities, default={}, help='comma-separated name or name:seats')
    dep.add_argument('--forge', default='', help='https base a missing checkout is cloned from: <forge>/<repo>.git')
    dep.add_argument('--root', type=Path, default=Path.home() / 'src', help='checkouts live in <root>/<repo>')
    dep.add_argument('--ref', default='integrate/main', help='the branch a new clone follows')
    dep.add_argument('--delegates', type=_logins, default=(), help='[reserve] delegates: who else may reserve it')
    dep.add_argument('--dry-run', action='store_true', help='print every action; change nothing')
    verbs.add_parser('serve', help="the Task's action: serve every [serve] repo under one lock")
    return parser


def _probe(programs: Programs, capabilities: Mapping[str, Any]) -> list[str]:
    emit('[probe] uv, git' + ''.join(f', {name}' for name in ('node', 'jmag') if name in capabilities))
    wanted = ['uv', 'git', *(['node'] if 'node' in capabilities else [])]
    missing = [f'{tool} not on PATH: {_REMEDIES[tool]}' for tool in wanted if programs.which(tool) is None]
    if 'jmag' in capabilities and (absent := [p for p in JMAG_PROGIDS if programs.com(p) is None]):
        missing.append(f'COM class {", ".join(absent)} not registered: {_JMAG_REMEDY}')
    return missing


def _url(programs: Programs, checkout: Path, name: str, forge: str) -> str:
    if (checkout / '.git').exists():
        return _read([*programs.git, '-C', str(checkout), 'remote', 'get-url', 'origin']).stdout.strip()
    return f'{forge.rstrip("/")}/{name}.git' if forge else ''


def _credentials(programs: Programs, urls: Mapping[str, str]) -> list[str]:
    emit('[credential] git ls-remote per repo, prompting off: only a stored credential answers')
    denied = []
    for name, url in urls.items():
        argv = [*programs.git, '-c', 'credential.interactive=never', 'ls-remote', '-q', url, 'HEAD']
        rc = _read(argv, _NO_PROMPT).returncode
        emit(f'  {name}: {"ok" if rc == 0 else f"refused (exit {rc})"}')
        if rc:
            denied.append(name)
    return denied


@dataclass(frozen=True)
class _Moved:
    """A checkout step's outcome: its exit, whether HEAD moved, and why it was refused."""

    rc: int
    moved: bool = False
    why: str = ''


def _checkout(step: Step, programs: Programs, checkout: Path, *, url: str, ref: str) -> _Moved:
    if not (checkout / '.git').exists():
        clone = [*programs.git, 'clone', '-q', '-b', ref, url, str(checkout)]
        return _Moved(step.change(f'{checkout.name}: git clone -b {ref} {url} {checkout}', clone), moved=True)
    git = [*programs.git, '-C', str(checkout)]
    if _read([*git, 'status', '--porcelain']).stdout.strip():
        return _Moved(2, why=f'{checkout} has local changes; commit or clean them, then re-run')
    if step.dry:
        return _Moved(step.change(f'{checkout.name}: git fetch, then fast-forward to its upstream when behind', []))
    return _fast_forward(step, git, checkout.name)


def _fast_forward(step: Step, git: Sequence[str], name: str) -> _Moved:
    if rc := step.change(f'{name}: git fetch', [*git, 'fetch', '-q']):
        return _Moved(rc)
    head, upstream = (_read([*git, 'rev-parse', rev]).stdout.strip() for rev in ('HEAD', '@{u}'))
    if not upstream:
        return _Moved(2, why=f'{name} tracks no upstream; `git branch -u origin/<ref>` in it, then re-run')
    if head == upstream:
        emit(f'  {name}: current at {head[:12]}')
        return _Moved(0)
    merge = [*git, 'merge', '--ff-only', '-q', '@{u}']
    return _Moved(step.change(f'{name}: fast-forward {head[:12]} -> {upstream[:12]}', merge), moved=True)


def _venv(step: Step, programs: Programs, checkout: Path, name: str, *, moved: bool) -> int:
    if _venv_python(checkout).is_file() and not moved:
        emit(f'  {name}: .venv current')
        return 0
    # The door's own rule: a primary checkout's environment moves only from that checkout.
    bootstrap = [*programs.bootstrap, str(checkout)]
    return step.change(f'{name}: -m lab_commons.dev.dep --bootstrap {checkout}', bootstrap, cwd=checkout)


def _hooks(step: Step, programs: Programs, checkout: Path, name: str) -> int:
    if step.dry and not _venv_python(checkout).is_file():
        return step.change(f'{name}: hook_install --install, when its hooks are not live', [])
    hook = [*programs.python_of(checkout), '-m', 'lab_commons.dev.hook_install', '--repo', str(checkout)]
    rc = _read(hook).returncode
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
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_name(path.name + '.new')
    staged.write_text(after, encoding='utf-8')
    staged.replace(path)
    return 0


def _task(step: Step, programs: Programs, lab: Path) -> int:
    emit(f'[task] {servetask.TASK}')
    want = servetask.definition_of(lab)
    query = _read([*programs.schtasks, *servetask.query_argv()[1:]])
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
    emit('[venvs] -m lab_commons.dev.dep --bootstrap where missing or moved')
    for name, co in checkouts.items():
        if name not in refused and (rc := _venv(step, tools, co, name, moved=done[name].moved)):
            refused[name] = f'its venv bootstrap exited {rc}'
    emit('[hooks] hook_install --install where not live')
    for name, co in checkouts.items():
        if name not in refused and (rc := _hooks(step, tools, co, name)):
            refused[name] = f'its hook install exited {rc}'
    return refused


def deploy(argv: Sequence[str], *, programs: Programs | None = None) -> int:
    """Run the deployment *argv* asks for; 0 done, 2 refused (the message names the remedy)."""
    args = _parser().parse_args(['deploy', *argv])
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
    tables['serve'] = {'repos': [name for name in args.repos if name not in refused], 'root': str(args.root)}
    if args.delegates:
        tables['reserve'] = {'delegates': list(args.delegates)}
    rc = _machine_file(step, tables) or _task(step, tools, checkouts[LAB_COMMONS])
    for name, why in refused.items():
        tools.alarm(Alarm(RUN, urls[name], f'workstation deploy refused {name}; this box does not serve it', why))
        emit(f'deploy refused {name} (left out of [serve] repos): {why}', err=True)
    return rc or (2 if refused else 0)


def serve(*, run: Callable[..., Any] = subprocess.run, lock: Path | None = None, out: IO[str] | None = None) -> int:
    """``forge serve`` in each ``[serve] repos`` checkout, under one lock; the worst exit.

    Every child starts with no console window; *out*, when given, receives its stdout and stderr.
    """
    table = section('serve')
    repos, root = table.get('repos'), table.get('root')
    if not (isinstance(repos, list) and repos and isinstance(root, str)):
        emit(f'[serve] refused: no [serve] repos and root in {config_path()}; run `workstation deploy`', err=True)
        return 2
    with held(lock or default_lock()) as mine:
        if not mine:
            emit('[serve] another forge serve holds the lock; this one does nothing', err=True)
            return 0
        worst = 0
        for name in repos:
            checkout = Path(root) / name
            python = _venv_python(checkout)
            if not python.is_file():
                emit(f'[serve] {name}: no {python}; re-run `workstation deploy`', err=True)
                worst = max(worst, 2)
                continue
            emit(f'[serve] {name}', flush=True)
            argv = [str(python), '-m', 'lab_commons.dev.forge', 'serve']
            streams = {'stdin': subprocess.DEVNULL, 'stdout': out, 'stderr': subprocess.STDOUT} if out else {}
            rc = run(argv, cwd=checkout, check=False, **streams, **servetask.windowless()).returncode
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
