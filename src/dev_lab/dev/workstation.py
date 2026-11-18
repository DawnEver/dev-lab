"""A WINDOWS WORKSTATION'S DEPLOY, in one run: ``python -m dev_lab.dev.workstation deploy``.

A WORKSTATION NEVER SERVES A MERGE'S PARTS (user ruling 2026-11-16): only GitHub Actions (an ``actions`` repo)
and the HPC accounts (the roles the family binds to them, :mod:`dev_lab.dev.roles`) produce. The deploy makes the box a
declared, current client -- capabilities, checkouts, venvs, hooks -- and nothing on it ticks.

It reuses the cluster deploy's run-or-print :class:`~dev_lab.dev.hpcaccount.steps.Step`.

``deploy --repos <repo>,... (--capabilities workstation,jmag:4 | --role light) [--forge <https base>]
[--ref BRANCH] [--dry-run]``, each step reporting and safe to repeat. A ``--role`` is a declared profile
(:data:`ROLES`: its capabilities); ``template --role <role>`` prints the tables it writes. The ``light`` role
refuses every :data:`HEAVY` tool in ``--capabilities``.
Nothing is reserved for the person at the box (user ruling 2026-10-25): they DECLARE their use as a ledger
claim (``python -m lab_commons.box claim``).

1-2. PROBE and CREDENTIAL (:mod:`dev_lab.dev.workstationprobe`): the tools and COM classes the declared
   capabilities need, and a stored git credential for every repo. Every missing item is refused at once,
   each with its remedy. Only a host the registry gives the ``forge`` role deploys
   (:mod:`dev_lab.dev.workstationregistry`).
3. CHECKOUTS at ``<forge home>/repos/<repo>`` (:func:`checkout`), the dev-lab kit always among them, derived
   from the platform data dir and never configured (user ruling 2026-10-26: they are neither user-visible
   nor shared with dev checkouts): clone ``<forge>/<repo>.git`` at ``--ref``, or fast-forward an existing
   CLEAN checkout to its upstream (the KIT REFRESH); a dirty one is refused.
4. VENVS: ``-m dev_lab.dev.dep --bootstrap <checkout>`` when the venv is missing or its ``pyproject.toml``
   or ``uv.lock`` changed since its last sync (a stamp in the venv, written only after a sync succeeds).
5. HOOKS: ``-m dev_lab.dev.hook_install --install`` in each checkout whose hooks are not live.
6. MACHINE FILE (:mod:`lab_commons.config`): ``[capabilities.<name>]`` (``seats`` from ``name:N``; a ``jmag``
   row also ``in_use = { process = JMAG_SOLVER_IMAGES }``, so a solve a person starts is a seat taken),
   merged in place. ``[serve]`` is never written and a present one is removed
   (:func:`dev_lab.dev.rolecheck.host_refusals`). Every RETIRED ``[capabilities.<name>]`` table is
   removed -- one retired into ``[runtimes.<name>]`` has its keys carried there; every other table, key and
   comment is kept, and ``--dry-run`` prints the diff.
7. RETIRED TASK: the ``lab-forge-serve`` Scheduled Task an older deploy registered (:data:`RETIRED_TASK`) is
   deleted where it is still installed, so nothing ticks on the box.

``--dry-run`` reads but changes nothing. A second run changes nothing.

A REFUSAL IN STEPS 3-5 BELONGS TO ITS REPO (incident 2026-10-13, the cluster deploy's twin): the repo is
reported with its reason and skipped by the later steps; the deploy finishes for the others, raises one forge
``run`` alarm per refused repo (:mod:`dev_lab.dev.forgealarm`), and exits 2 naming each.

A RETIRED VERB OR FLAG is refused by name with its ruling and its door (:data:`RETIRED_VERBS`,
:data:`RETIRED_FLAGS`).
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
from typing import Final

from lab_commons.hpc.retired import refusal
from lab_commons.log import emit

from dev_lab.dev.forgealarm import RUN, Alarm, sound
from dev_lab.dev.hostrefresh import Moved, follow, network, read, sync_venv
from dev_lab.dev.hpcaccount.spec import KIT
from dev_lab.dev.hpcaccount.steps import Step, Tools
from dev_lab.dev.servelock import forge_home
from dev_lab.dev.venvfollow import venv_python
from dev_lab.dev.workstationfile import ROLES, capabilities, deploy_tables, machine_file, role_refusal, template
from dev_lab.dev.workstationprobe import CREDENTIAL_REMEDY, com_server, missing, refused_credentials
from dev_lab.dev.workstationregistry import forge_refusal, this_computer

__all__ = ['RETIRED_FLAGS', 'RETIRED_TASK', 'RETIRED_VERBS', 'Programs', 'checkout', 'deploy', 'main', 'repos']

#: The Scheduled Task an older deploy registered to serve from this box; a deploy deletes it where installed.
RETIRED_TASK: Final = 'lab-forge-serve'

_PRODUCERS: Final = (
    "a workstation never serves a merge's parts (user ruling 2026-11-16): the executors the family layer binds "
    'each role to produce them (dev_lab.dev.roles)'
)
#: A retired ``workstation`` verb -> its ruling and door; refused by name, never parsed.
RETIRED_VERBS: Final = {
    'serve': f'{_PRODUCERS}; read where a sha stands with `python -m dev_lab.dev.forge queue`, and re-run '
    f'`python -m dev_lab.dev.workstation deploy` to delete a {RETIRED_TASK} Task still installed',
}
#: A retired ``workstation deploy`` flag -> its remedy; refused by name, never silently ignored.
RETIRED_FLAGS: Final = {
    '--root': 'checkouts are derived as <forge home>/repos/<repo> (dev_lab.dev.servelock.forge_home); drop the flag',
}


def repos(home: Path) -> Path:
    """Where every deployed checkout lives under the forge *home*: ``<home>/repos``, derived and never configured."""
    return home / 'repos'


def checkout(home: Path, repo: str) -> Path:
    """The deployed checkout of *repo* under the forge *home*."""
    return repos(home) / repo


def _retired(word: str) -> str | None:
    """The refusal of *word* when it is a retired ``workstation`` verb or flag, naming its door."""
    if word in RETIRED_VERBS:
        return f'`workstation {word}` is retired: {RETIRED_VERBS[word]}'
    if word in RETIRED_FLAGS:
        return f'`workstation {word}` is retired: {RETIRED_FLAGS[word]}'
    return refusal('workstation', word)


def _own_python(checkout: Path) -> tuple[str, ...]:
    return (str(venv_python(checkout)),)


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
    home: Path = field(default_factory=forge_home)  # the forge's machine home; checkouts in <home>/repos
    alarm: Callable[[Alarm], object] = sound
    computer: str = field(default_factory=this_computer)


def _repos(text: str) -> tuple[str, ...]:
    names = tuple(dict.fromkeys(part.strip() for part in text.split(',') if part.strip()))
    if not names:
        msg = 'name at least one repo to deploy'
        raise argparse.ArgumentTypeError(msg)
    return names


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.workstation', description=__doc__.splitlines()[0])
    verbs = parser.add_subparsers(dest='verb', required=True)
    dep = verbs.add_parser('deploy', help='declare this workstation and keep its checkouts current')
    dep.add_argument(
        '--repos', type=_repos, required=True, help=f'comma-separated, the repos kept here; {KIT} is always kept'
    )
    dep.add_argument('--capabilities', type=capabilities, default=None, help='comma-separated name or name:seats')
    dep.add_argument('--role', choices=sorted(ROLES), help='a declared profile (ROLES): its capabilities')
    dep.add_argument('--forge', default='', help='https base a missing checkout is cloned from: <forge>/<repo>.git')
    dep.add_argument('--ref', default='integrate/main', help='the branch a new clone follows')
    dep.add_argument('--dry-run', action='store_true', help='print every action; change nothing')
    tpl = verbs.add_parser('template', help='print the machine-file tables a --role deploy writes')
    tpl.add_argument('--role', choices=sorted(ROLES), required=True)
    return parser


def _url(programs: Programs, checkout: Path, name: str, forge: str) -> str:
    if (checkout / '.git').exists():
        return read([*programs.git, '-C', str(checkout), 'remote', 'get-url', 'origin']).stdout.strip()
    return f'{forge.rstrip("/")}/{name}.git' if forge else ''


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


def _retire_task(step: Step, programs: Programs) -> int:
    """Delete the :data:`RETIRED_TASK` an older deploy registered, where it is still installed."""
    emit(f'[task] {RETIRED_TASK} (retired: a workstation never serves)')
    if read([*programs.schtasks, '/Query', '/TN', RETIRED_TASK]).returncode:
        emit('  none installed')
        return 0
    delete = ['/Delete', '/TN', RETIRED_TASK, '/F']
    return step.change(subprocess.list2cmdline(['schtasks', *delete]), [*programs.schtasks, *delete])


def _preflight(args: argparse.Namespace, tools: Programs, checkouts: Mapping[str, Path]) -> dict[str, str] | str:
    """Every read-only refusal before anything changes; the clone url of each repo when none applies."""
    if not tools.windows:
        return 'a workstation deploy is Windows-only; a cluster account deploys with `hpcaccount deploy`'
    if why := forge_refusal(tools.computer):
        return f'not a forge host: {why}'
    if absent := missing(tools.which, tools.com, args.capabilities):
        for line in absent:
            emit(f'  {line}', err=True)
        return f'{len(absent)} missing; install each as named, then re-run'
    urls = {name: _url(tools, co, name, args.forge) for name, co in checkouts.items()}
    if unknown := [name for name, url in urls.items() if not url]:
        return f'no checkout of {", ".join(unknown)} in {repos(tools.home)}; pass --forge <https base>'
    if denied := refused_credentials(tools.git, urls):
        return f'no stored git credential reads {", ".join(denied)}; {CREDENTIAL_REMEDY}'
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
    # the kit is kept current on every host (ruling 2026-10-29)
    checkouts = {name: checkout(tools.home, name) for name in dict.fromkeys((KIT, *args.repos))}
    try:
        urls = _preflight(args, tools, checkouts)
    except ValueError as bad:
        urls = str(bad)
    if isinstance(urls, str):
        emit(f'deploy refused: {urls}', err=True)
        return 2
    step = Step(Tools(git=tools.git), dry=args.dry_run)
    refused = _checkouts(step, tools, checkouts, urls, args.ref)
    rc = machine_file(step, deploy_tables(args.capabilities)) or _retire_task(step, tools)
    for name, why in refused.items():
        tools.alarm(
            Alarm(RUN, urls[name], f'workstation deploy refused {name}; this box does not keep it current', why)
        )
        emit(f'deploy refused {name} (its checkout is not kept current): {why}', err=True)
    return rc or (2 if refused else 0)


def main(argv: Sequence[str] | None = None) -> int:
    """``deploy ...`` or ``template``; a retired verb or flag is refused by name with its door."""
    args = list(sys.argv[1:] if argv is None else argv)
    words = (word.split('=', 1)[0] for word in args)
    if refused := next(filter(None, map(_retired, words)), None):
        emit(refused, err=True)
        return 2
    if args[:1] == ['deploy']:
        return deploy(args[1:])
    parsed = _parser().parse_args(args)
    emit(template(parsed.role).rstrip())
    return 0


if __name__ == '__main__':
    sys.exit(main())
