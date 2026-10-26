"""``python -m dev_lab.dev.hpchost deploy`` -- make this account's login host a ``forge serve`` host, in one run.

WHAT IS DEPLOYED IS DATA in this account's machine file (:mod:`lab_commons.config`, ``[deploy]``) -- never in
a tracked file, since the forge, its repos and the login host are private to the deployment::

    [deploy]
    host = "<login host>"          # the ONE host whose crontab serves this account (cron is per host)
    root = "src"                   # the served checkouts live in ~/<root>/<name>
    python = "3.13"                # a uv-managed CPython: manylinux wheels run on an old glibc
    slurm_account = "<account>"    # only when sacctmgr names several
    partitions = ["<partition>", ...]
    repos = [{ name = "dev-lab", url = "<https url>", ref = "<branch>" }, { name = "<repo>", ... }, ...]
    # an entry may add serve = false: checked out and installed, its forge queue not served by this account

    [schedule]
    tick_minutes = 15              # the cron period (divides 60; default 5) -- also what the host card is judged by

The first run DECLARES it with ``--host <host> --repo <name>=<url>@<ref> ... --partition <p> ...`` (written
once; a later run with flags that disagree is refused, naming the file); every later run reads it.
``dev-lab`` (the kit) is always among the repos: every tick RUNS it and its own line is the one writer of
its checkout; whether this account also serves dev-lab's queue is that entry's ``serve``.

STEPS, each one reporting, each one safe to repeat: refuse off the declared host; check the account BEFORE
anything changes (:mod:`dev_lab.dev.hpchost.account`: git's credential helper and its store, every repo's
``git ls-remote``, and the forge API calls a tick makes); write this account's own ``[[hpc.grant]]`` when
it has none; prove the serve's git (``git merge-tree --write-tree``, git >= 2.38) on a toy repository --
IN the tick's environment (cron's PATH, then this account's grant ``setup``, which every cron line runs
before its tick) -- or refuse naming that environment; clone or update each checkout; install ``uv`` and
every declared ``needs`` whose ``--version`` does not run in the tick's environment, or refuse naming it;
make the login shell's PATH name the tick's user installs (one marked line in the files bash reads, written
once, the file backed up first); build each ``.venv`` with the repo's own ``[tool.lab_commons.hpc] install``
(and its ``native`` build) -- exactly what its committed lock pins, nothing installed over it -- skipped when
the key of its inputs (the lock's hash among them) is unchanged; warn, naming the recipe, when a repo declares an rclone
artefact store this account's remote cannot reach (:func:`lab_commons.hpc.rclone.probe`; parts with outputs
are then not claimed here); replace this tool's marked crontab lines (one per served repo and the kit, every
``[schedule] tick_minutes`` at a minute offset derived per account, under ``flock -n``)
and touch no other line; run one tick of each and print it. ``--dry-run`` reads but changes nothing;
``--remove`` deletes the marked lines only. No credential is ever printed.

A REFUSAL BELONGS TO THE REPO THAT EARNED IT (incident 2026-10-13: one repo still declaring a retired
``[tool.lab_commons.<table>]`` stopped the whole deploy at ``[tools]``, so the host served none of three).
From ``[checkouts]`` on, every per-repo step handles each repo on its own: a repo whose step fails, whose
need cannot be installed, or whose declaration is refused (``REFUSALS`` of :mod:`lab_commons.hpc.declared`:
``RetiredTable``, ``OutdatedKit``, ``InvalidDeclaration``) is reported with its reason and skipped by every
later step -- it gets no
crontab line, and the line it had is removed, so a broken line never runs. The deploy finishes for the
others, then exits 2 naming each refused repo and raising one forge ``run`` alarm per repo (through
:mod:`dev_lab.dev.forgealarm` in a subprocess, as a person sounds one).
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import socket
import sys
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.config import config_path
from lab_commons.hpc.declared import REFUSALS
from lab_commons.hpc.rclone import declared_remote, probe
from lab_commons.log import emit

from dev_lab.dev.hpchost.account import ApiCheck, auth_check, credentials, grant
from dev_lab.dev.hpchost.checks import (
    LOGIN_MARK,
    MERGE_TREE_GIT,
    login_files,
    login_line,
    merge_tree_refusal,
    runs,
    tool_plan,
)
from dev_lab.dev.hpchost.spec import (
    DEFAULT_PYTHON,
    DEFAULT_ROOT,
    KIT,
    Deployment,
    Repo,
    checkout_of,
    cron_lines,
    grant_setup,
    load,
    merge_crontab,
    parse_repo,
    render,
    tick_command,
    tick_dirs,
    tick_environment,
)
from dev_lab.dev.hpchost.steps import Step, Tools, build, declared, update

__all__ = ['deploy', 'main']


_which = shutil.which
_runs = runs


def _proves(git: Sequence[str], scratch: Path) -> str:
    """``''`` when the *git* argv runs the serve's trial merge (:func:`merge_tree_refusal`); else why not."""
    return merge_tree_refusal(git, scratch)


#: Raises one forge alarm: ``(repo url, subject, body)``.
AlarmSink = Callable[[str, str, str], object]

#: The served repos refused so far, by name, each with its reason; every later per-repo step skips them.
Refused = dict[str, str]


def _crontab(step: Step, lines: Sequence[str]) -> int:
    listed = step.read([*step.tools.crontab, '-l'])
    current = listed.stdout if listed.returncode == 0 else ''
    if listed.returncode and 'no crontab' not in listed.stderr:
        emit(f'  crontab -l exited {listed.returncode}: {listed.stderr.strip()}', err=True)
        return 2
    wanted = merge_crontab(current, lines)
    if wanted == current:
        emit(f'  crontab: the {len(lines)} marked line(s) are already in place')
        return 0
    return step.change(
        f'crontab: write {len(lines)} marked line(s), every other line kept', [*step.tools.crontab, '-'], stdin=wanted
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpchost deploy', description=__doc__.splitlines()[0])
    parser.add_argument('--config', type=Path, help='the machine file holding [deploy] (default: lab_commons.config)')
    parser.add_argument('--host', help='declare: the one login host serving this account')
    parser.add_argument(
        '--repo', type=parse_repo, action='append', default=[], help='declare: <name>=<https url>@<branch>'
    )
    parser.add_argument('--root', default=DEFAULT_ROOT, help='declare: checkouts live in ~/<root>/<name>')
    parser.add_argument('--python', default=DEFAULT_PYTHON, help='declare: the uv-managed interpreter request')
    parser.add_argument('--slurm-account', default='', help="declare: the grant's account, when Slurm names several")
    parser.add_argument('--partition', action='append', default=[], help='declare: a partition the grant may use')
    parser.add_argument('--dry-run', action='store_true', help='print every action; change nothing')
    parser.add_argument('--remove', action='store_true', help='delete the marked crontab lines only')
    return parser


def _declared(args: argparse.Namespace, path: Path) -> Deployment | str:
    """The declared deployment (stored, else from the flags); a refusal is returned as its message."""
    stored = load(path)
    if not (args.host or args.repo):
        return stored or (
            f'no [deploy] in {path}: declare it once with --host <login host> --repo <name>=<https url>@<branch> ...'
        )
    if not (args.host and args.repo):
        return 'a declaration needs both --host and at least one --repo'
    given = Deployment(args.host, args.root, args.python, tuple(args.repo), args.slurm_account, tuple(args.partition))
    if stored is not None and stored != given:
        return f'{path} already declares a different [deploy]; edit it there, or run without --host/--repo'
    return given


def _resolve(args: argparse.Namespace, path: Path) -> Deployment | str:
    """The declared deployment, refused unless it declares the kit (dev-lab) -- the code every tick runs."""
    spec = _declared(args, path)
    if isinstance(spec, Deployment) and KIT not in {repo.name for repo in spec.repos}:
        return f'every tick runs {KIT}, so the host checks it out: add --repo {KIT}=<https url>@<branch>'
    return spec


def _declare(step: Step, spec: Deployment, path: Path) -> int:
    """Store a first declaration once the host and every credential have passed."""
    if load(path) is not None:
        return 0
    emit('[declare]')
    if step.dry:
        emit(f'  [dry-run] declare [deploy] in {path}')
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as out:
        out.write(render(spec))
    emit(f'  declared [deploy] in {path}')
    return 0


def _each(step: Step, spec: Deployment, home: Path, title: str, act: Callable[..., int], *, refused: Refused) -> int:
    """*act* on each repo not yet refused; a failing or refused one is recorded in *refused*, never stops the rest."""
    emit(title)
    for repo in _healthy(spec, refused):
        try:
            rc = act(step, spec, home, repo)
        except REFUSALS as why:
            _refuse(refused, repo, str(why))
            continue
        if rc:
            _refuse(refused, repo, f'{title.split("]", 1)[0].lstrip("[")} exited {rc}')
    return 0


def _healthy(spec: Deployment, refused: Refused) -> list[Repo]:
    return [repo for repo in spec.repos if repo.name not in refused]


def _refuse(refused: Refused, repo: Repo, why: str) -> None:
    emit(f'  {repo.name}: refused, skipped by every later step: {why}', err=True)
    refused[repo.name] = why


def _serve_git(step: Step, home: Path, path: Path, slurm: Sequence[str], setup: list[str]) -> int:
    """Prove the tick's git runs merge-tree IN the tick's environment; the grant's setup goes into *setup*.

    The proof runs ``git`` under :func:`tick_environment` -- cron's PATH, then this account's grant setup -- the
    same prefix every cron line runs, so what is proven is what ticks. No silent fallback: a git that cannot
    trial-merge there serves nothing, so it refuses the deploy.
    """
    emit(f"[git] {MERGE_TREE_GIT}, in the tick's environment")
    user = step.read([*step.tools.id, '-un']).stdout.strip()
    loaded = grant_setup(path, user)
    environment = tick_environment(home, slurm, loaded)
    with tempfile.TemporaryDirectory() as scratch:
        why = _proves([*step.tools.sh, f'{environment}; exec git "$@"', 'git'], Path(scratch))
    if not why:
        emit(f'  git in `{environment}`: merge-tree --write-tree runs')
        setup.extend(loaded)
        return 0
    emit(
        f'deploy refused: every serve tick runs {MERGE_TREE_GIT} and the git in its environment '
        f'(`{environment}`) does not: {why}. Add setup = ["module load <git 2.38 or later>"] to this '
        f"account's [[hpc.grant]] in {path}, or link a qualifying git into ~/.local/bin, and re-run",
        err=True,
    )
    return 2


#: The Slurm commands a tick runs: it submits, then gathers and watches.
SLURM_TOOLS: Final = ('sbatch', 'sacct', 'squeue')


def _slurm_dirs() -> list[str] | str:
    """The directories ``sbatch``, ``sacct`` and ``squeue`` resolve in NOW; a missing one is refused by name."""
    found = {tool: _which(tool) for tool in SLURM_TOOLS}
    if missing := [tool for tool, where in found.items() if where is None]:
        return (
            f'{", ".join(missing)} not found on this PATH: a tick submits and gathers through Slurm. '
            'Run the deploy from a login shell where `command -v sbatch` answers'
        )
    return [str(Path(where).parent) for where in found.values() if where is not None]


def _tools(
    step: Step, spec: Deployment, home: Path, refused: Refused, *, slurm: Sequence[str], setup: Sequence[str]
) -> int:
    """``uv`` and each repo's ``needs``; a repo whose declaration, or a need of which, is refused is refused alone."""
    emit("[tools] uv and every declared `needs`, by `<tool> --version` in the tick's environment")
    needs: dict[str, tuple[str, ...]] = {}
    for repo in _healthy(spec, refused):
        try:
            needs[repo.name] = () if step.dry else declared(checkout_of(spec, home, repo)).needs
        except REFUSALS as why:
            _refuse(refused, repo, str(why))
    environment = tick_environment(home, slurm, setup)
    wanted = [need for each in needs.values() for need in each]
    installs, failed = tool_plan(wanted, found=lambda tool: _runs(step.tools.sh, environment, tool))
    for tool, script in installs:
        if step.change(f'install {tool}: {script}', [*step.tools.sh, script]):
            failed.append(tool)
    remedy = (
        f'does not run (`--version`) in the tick environment (`{environment}`) and is not installable here; '
        'ask for it on the login node, or link it into ~/.local/bin, and re-run'
    )
    if 'uv' in failed:  # every tick needs it: no repo can be served
        emit(f'deploy refused: uv {remedy}', err=True)
        return 2
    for repo in _healthy(spec, refused):
        if lacking := [need for need in needs.get(repo.name, ()) if need in failed]:
            _refuse(refused, repo, f'{", ".join(lacking)} {remedy}')
    return 0


def _cron(
    step: Step, spec: Deployment, home: Path, refused: Refused, *, slurm: Sequence[str], setup: Sequence[str]
) -> int:
    """One marked line per repo not refused; a refused repo's line is removed, so a broken line never runs."""
    emit('[cron] one marked line per served repo')
    if not step.dry:
        (home / '.cache').mkdir(parents=True, exist_ok=True)
    lines = cron_lines(replace(spec, repos=tuple(_healthy(spec, refused))), home, slurm=slurm, setup=setup)
    rc = _crontab(step, lines)
    for line in lines:
        emit(f'  {line}')
    return rc


def _tick(
    step: Step, spec: Deployment, home: Path, repo: Repo, *, slurm: Sequence[str] = (), setup: Sequence[str] = ()
) -> int:
    command = tick_command(spec, home, repo, log=False, slurm=slurm, setup=setup)
    rc = step.change(f'tick {repo.name}: {command}', [*step.tools.sh, command])
    if not step.dry:
        busy = ' (1 also means a tick of this host is still running)' if rc == 1 else ''
        emit(f'  tick {repo.name} exited {rc}{busy}')
    return 0  # a red tick is reported, never a reason to undo the deployment


def _artefacts(step: Step, spec: Deployment, home: Path, repo: Repo) -> int:
    remote = declared_remote(checkout_of(spec, home, repo))
    if not remote:
        emit(f'  {repo.name}: no rclone artefact store declared')
        return 0
    why = probe(remote, rclone=step.tools.rclone)
    emit(f'  {repo.name}: ' + (f'WARNING {why}' if why else 'the rclone remote answers'), err=bool(why))
    return 0  # a warning, never a refusal: most parts declare no large outputs


def _sound(url: str, subject: str, body: str) -> object:
    """One forge ``run`` alarm, raised by :mod:`dev_lab.dev.forgealarm` in a subprocess."""
    argv = [sys.executable, '-m', 'dev_lab.dev.forgealarm', 'run', url, subject, body]
    return _door.run(argv, capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)


def _report(spec: Deployment, refused: Refused, host: str, alarm: AlarmSink) -> int:
    """0 when every repo is served; else name each refused repo, alarm its owner, and return 2."""
    if not refused:
        return 0
    for repo in spec.repos:
        if why := refused.get(repo.name):
            alarm(repo.url, f'the deploy on {host} refused {repo.name}; it is not served there', why)
            emit(f'deploy refused {repo.name} (not served, no crontab line): {why}', err=True)
    emit(f'deploy finished for: {", ".join(r.name for r in _healthy(spec, refused)) or "no repo"}', err=True)
    return 2


def _login(step: Step, home: Path) -> int:
    """One marked :func:`login_line` in each of :func:`login_files`, written once, each file backed up first."""
    emit("[login] the login shell's PATH names the tick's user installs")
    line = login_line(home)
    for path in login_files(home):
        if path.is_file() and LOGIN_MARK in path.read_text(encoding='utf-8', errors='replace'):
            emit(f'  {path}: current')
            continue
        file, backup = shlex.quote(str(path)), shlex.quote(f'{path}.lab-deploy.bak')
        keep = f'[ ! -e {file} ] || [ -e {backup} ] || cp -p {file} {backup}'
        script = f'{{ {keep}; }} && echo {shlex.quote(line)} >> {file}'
        if rc := step.change(f'{path}: back up, then append {line}', [*step.tools.sh, script]):
            return rc
    return 0


def deploy(
    argv: Sequence[str],
    *,
    home: Path,
    hostname: str,
    tools: Tools | None = None,
    api: ApiCheck | None = None,
    alarm: AlarmSink = _sound,
) -> int:
    """Run the deployment *argv* asks for; 0 done, 2 refused (the message names the remedy and refused repos)."""
    args = _parser().parse_args(list(argv))
    path = args.config or config_path()
    spec = _resolve(args, path)
    if isinstance(spec, str):
        emit(f'deploy refused: {spec}', err=True)
        return 2
    short = hostname.split('.', 1)[0]
    emit(f'[host] account {os.environ.get("USER") or os.environ.get("USERNAME", "?")} on {short}')
    if short != spec.host:
        emit(
            f'deploy refused: this account serves from {spec.host} ([deploy] host in '
            f'{path}); this is {short}. ssh to {spec.host} and run it there.',
            err=True,
        )
        return 2
    path_env = os.pathsep.join([*tick_dirs(home)[:2], os.environ.get('PATH', '')])
    step = Step(tools or Tools(), dry=args.dry_run, path=path_env)
    if args.remove:
        emit('[cron] removing the marked lines')
        return _crontab(step, [])
    check = api or auth_check
    slurm = _slurm_dirs()
    if isinstance(slurm, str):
        emit(f'deploy refused: {slurm}', err=True)
        return 2
    refused: Refused = {}
    setup: list[str] = []  # the grant's setup lines: every tick runs inside them
    artefacts = '[artefacts] the rclone remote, where a repo declares one'
    phases = (
        lambda: credentials(step, spec, home, check),
        lambda: grant(step, spec, path, hostname),
        lambda: _declare(step, spec, path),
        lambda: _serve_git(step, home, path, slurm, setup),
        lambda: _each(step, spec, home, f'[checkouts] under ~/{spec.root}', update, refused=refused),
        lambda: _tools(step, spec, home, refused, slurm=slurm, setup=setup),
        lambda: _login(step, home),
        lambda: _each(step, spec, home, f'[venvs] python {spec.python} (uv-managed)', build, refused=refused),
        lambda: _each(step, spec, home, artefacts, _artefacts, refused=refused),
        lambda: _cron(step, spec, home, refused, slurm=slurm, setup=setup),
        lambda: _each(
            step,
            spec,
            home,
            '[tick] one now, per repo',
            lambda *a: _tick(*a, slurm=slurm, setup=setup),
            refused=refused,
        ),
    )
    for phase in phases:
        if rc := phase():
            return rc
    return _report(spec, refused, short, alarm)


def main(argv: Sequence[str]) -> int:
    """The CLI entry: this box's home and its fully qualified name (the grant's ssh host)."""
    return deploy(argv, home=Path.home(), hostname=socket.getfqdn())
