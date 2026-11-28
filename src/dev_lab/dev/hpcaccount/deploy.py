"""``python -m dev_lab.dev.hpcaccount deploy`` -- make this account's login host a ``forge serve`` host, in one run.

WHAT IS DEPLOYED IS DATA in this account's machine file (:mod:`lab_commons.config`, ``[deploy]``) -- never in
a tracked file, since the forge, its repos and the login host are private to the deployment::

    [deploy]
    host = "<login host>"          # serving: the ONE node whose cron serves it; research: any grant login host
    root = "<absolute root>"       # the cluster's declared root: <root>/repos/<name> (lab_commons.hpc.layout)
    python = "<x.y>"               # a uv-managed CPython (manylinux wheels run on an old glibc); default and
                                   # the only one a family repo installs on: the family Python (pythontoolchain)
    slurm_account = "<account>"    # only when sacctmgr names several
    partitions = ["<partition>", ...]
    role = "verification"          # or "research": only a verification account serves (user ruling 2026-11-06)
    repos = [{ name = "dev-lab", url = "<https url>", ref = "<branch>" }, { name = "<repo>", ... }, ...]
    # served only where the family binds a role of the repo to this account (dev_lab.dev.roles)

    [schedule]
    tick = "15 min"                # the cron period (whole minutes dividing an hour; default "5 min") -- also what
                                   # the host card is judged by
    tick_wall = "40 min"           # how long one tick may hold its lock before it ends itself (default "40 min")

The first run DECLARES it with ``--host <host> --repo <name>=<url>@<ref> ... --partition <p> ... --role <r>`` (written
once; a later run with flags that disagree is refused, naming the file); every later run reads it.
``dev-lab`` (the kit) is always among the repos: every tick RUNS from it.

STEPS, each one reporting, each one safe to repeat: refuse an undeclared ``role``; refuse off the declared host;
check the account BEFORE anything changes (:mod:`dev_lab.dev.hpcaccount.account`: git's credential helper and
its store, every repo's ``git ls-remote``, and the forge API calls a tick makes); refuse a stored forge
credential that may push or administer a forge-hosted repo, or is not the role's ``reader``, when the role is
``read_only`` (else reported; :mod:`dev_lab.dev.hpcaccount.division`, user rulings 2026-11-09); write this account's own
``[[hpc.grant]]`` when it has none; prove the serve's git (``git merge-tree --write-tree``, git >= 2.38) on a toy
repository -- IN the tick's environment (cron's PATH, then this account's grant ``setup``, which every cron line runs
before its tick) -- or refuse naming that environment; state the quota and refuse what cannot fit
(:mod:`dev_lab.dev.hpcaccount.headroom`); clone or update each checkout; make the login shell's PATH name the
tick's user installs (one marked line in the files bash reads, written once, the file backed up first); for each
repo whose environment is not stamped with the key of its inputs (the lock's hash among them), ask its Slurm PREP JOB
(:mod:`dev_lab.dev.hpcaccount.prep`) -- NOTHING IS BUILT ON THE LOGIN NODE (ONE-LOGIN-POLLER, user ruling
2026-11-27): the venv, the native build, the ``needs`` probes and uv's pin all run in that job; warn, naming the
recipe, when a repo declares an rclone artifact store this account's remote cannot reach
(:func:`lab_commons.hpc.rclone.probe`; parts with outputs are then not claimed here); where the machine file
declares ``[capabilities.femm]`` and the family's pinned FEMM 5 is not installed, ask a Slurm job to build it
(``hpcaccount femm-build``, :mod:`dev_lab.dev.hpcaccount.femm`); replace this tool's marked crontab lines with the
account's ONE line (ONE-LOGIN-POLLER: one tick of every ticked repo, every ``[schedule] tick`` at a minute offset
derived per account, under one lock and wall, :mod:`dev_lab.dev.hpcaccount.tickwall`) and touch no other line -- the
cron runs the first tick. ``--dry-run`` reads but changes nothing;
``--remove`` deletes the marked lines only. A ``research`` account gets every step but the serve: its marked
lines are removed (each printed) and none is written (:func:`dev_lab.dev.hpcaccount.spec.ticked`). No credential is
ever printed.

A REFUSAL BELONGS TO THE REPO THAT EARNED IT (incident 2026-10-13: one repo still declaring a retired
``[tool.lab_commons.<table>]`` stopped the whole deploy at ``[tools]``, so the host served none of three).
From ``[checkouts]`` on, every per-repo step handles each repo on its own: a repo whose step fails, or whose
declaration is refused (``REFUSALS`` of :mod:`lab_commons.hpc.declared`:
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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

import lab_commons.launch as _door
from lab_commons import home as machinehome
from lab_commons.config import config_path
from lab_commons.hpc.declared import REFUSALS
from lab_commons.hpc.rclone import declared_remote, probe
from lab_commons.log import emit
from lab_commons.temp import TEMP_PREFIX

from dev_lab.dev import forgerunstate
from dev_lab.dev.hpcaccount import femm, headroom, prep
from dev_lab.dev.hpcaccount.account import ApiCheck, RoleCheck, auth_check, credentials, grant, reader, role_of
from dev_lab.dev.hpcaccount.checks import MERGE_TREE_GIT, merge_tree_refusal
from dev_lab.dev.hpcaccount.cimark import paused_refusal
from dev_lab.dev.hpcaccount.cronline import cron_lines
from dev_lab.dev.hpcaccount.declaration import parser, resolve, store
from dev_lab.dev.hpcaccount.deployhost import host_refusal
from dev_lab.dev.hpcaccount.division import account_role
from dev_lab.dev.hpcaccount.grantslice import Unreadable, grant_setup, machine_table
from dev_lab.dev.hpcaccount.spec import KIT, Deployment, Repo, checkout_of, load, tick_dirs, tick_environment
from dev_lab.dev.hpcaccount.steps import Step, Tools, crontab, declared, env_key, login, update
from dev_lab.dev.venvpointer import shell_interpreter

__all__ = ['deploy', 'femm_in_job', 'main', 'slurm_dirs']


_which = shutil.which


def _proves(git: Sequence[str], scratch: Path) -> str:
    """``''`` when the *git* argv runs the serve's trial merge (:func:`merge_tree_refusal`); else why not."""
    return merge_tree_refusal(git, scratch)


#: Raises one forge alarm: ``(repo url, subject, body)``.
AlarmSink = Callable[[str, str, str], object]

#: The served repos refused so far, by name, each with its reason; every later per-repo step skips them.
Refused = dict[str, str]


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


def _serve_git(
    step: Step,
    home: Path,
    path: Path,
    slurm: Sequence[str],
    setup: list[str],
    *,
    root: str,
    env: Sequence[tuple[str, str]] = (),
) -> int:
    """Prove the tick's git runs merge-tree IN the tick's environment; the grant's setup goes into *setup*.

    The proof runs ``git`` under :func:`tick_environment` -- cron's PATH, then this account's grant setup -- the
    same prefix every cron line runs, so what is proven is what ticks. No silent fallback: a git that cannot
    trial-merge there serves nothing, so it refuses the deploy.
    """
    emit(f"[git] {MERGE_TREE_GIT}, in the tick's environment")
    user = step.read([*step.tools.id, '-un']).stdout.strip()
    loaded = grant_setup(path, user)
    environment = tick_environment(home, root, slurm, loaded, env)
    with tempfile.TemporaryDirectory(prefix=TEMP_PREFIX) as scratch:
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


def slurm_dirs() -> list[str] | str:
    """The directories ``sbatch``, ``sacct`` and ``squeue`` resolve in NOW; a missing one is refused by name."""
    found = {tool: _which(tool) for tool in SLURM_TOOLS}
    if missing := [tool for tool, where in found.items() if where is None]:
        return (
            f'{", ".join(missing)} not found on this PATH: a tick submits and gathers through Slurm. '
            'Run the deploy from a login shell where `command -v sbatch` answers'
        )
    return [str(Path(where).parent) for where in found.values() if where is not None]


#: Every deploy phase, in order. The SERVING phases exist only to tick a verification account's queue: the scheduler
#: (cron) and what it alone needs -- the serve tick's git. Rule ``SCHEDULER-ONLY-FOR-SERVING``. No phase builds on the
#: login node (ONE-LOGIN-POLLER): ``prep`` and ``femm`` only ask Slurm jobs for what is not built yet.
PHASES: Final = (
    'credentials', 'reader', 'grant', 'store', 'runs', 'serve-git', 'headroom', 'checkouts', 'login', 'prep',
    'artifacts', 'femm', 'cron',
)  # fmt: skip
SERVING_PHASES: Final = frozenset({'serve-git', 'cron'})


def phases_of(*, serves: bool) -> tuple[str, ...]:
    """The deploy phases of a role that *serves* (its ``[hpc.roles]`` ``serves``), in order.

    A role that does not serve has none of :data:`SERVING_PHASES` -- no scheduler (user, 2026-11-20: a research host
    needs no cron).
    """
    return PHASES if serves else tuple(name for name in PHASES if name not in SERVING_PHASES)


def runs(step: Step) -> int:
    """The account's forge run files migrated once (FORMATS-MIGRATE-ONCE): a retired key renamed to its successor.

    The deploy is the fleet's one door onto an account, so it runs :func:`dev_lab.dev.forgerunstate.migrate` there;
    a dry run only names what it would rename. Each file is said; a clash is named and left for a person.
    """
    emit(f'[runs] the forge run files carry no retired key ({forgerunstate.directory()})')
    for line in forgerunstate.migrate(apply=not step.dry):
        emit(f'  {line}')
    return 0


def _cron(
    step: Step,
    spec: Deployment,
    home: Path,
    refused: Refused,
    *,
    serves: bool,
    slurm: Sequence[str],
    setup: Sequence[str],
) -> int:
    """The one marked line, ticking every repo not refused: a refused repo is left out, so a broken one never runs."""
    emit(
        f'[cron] the one marked line, every served repo ({spec.role} account: {"serves" if serves else "never serves"})'
    )
    if not step.dry:
        (home / '.cache').mkdir(parents=True, exist_ok=True)
    healthy = replace(spec, repos=tuple(_healthy(spec, refused)))
    lines = cron_lines(healthy, home, serves=serves, slurm=slurm, setup=setup)
    rc = crontab(step, lines)
    for line in lines:
        emit(f'  {line}')
    return rc


def _prep(step: Step, spec: Deployment, _home: Path, repo: Repo, submit: prep.Submit) -> int:
    """Ask *repo*'s Slurm prep job when its environment is not built for its inputs; nothing is built here.

    A repo declaring no install is refused (it could never be served); what the job door said is printed, never a
    refusal of the deploy: the tick serves the repo once the job published its environment.
    """
    checkout = checkout_of(spec, repo)
    if step.dry:
        step.change(f'{repo.name}: its prep job, when its environment is not built for its inputs', [])
        return 0
    builds = declared(checkout)
    if not builds.install:
        emit(f'  {repo.name} declares no [tool.lab_commons.hpc] install; refused', err=True)
        return 2
    key = env_key(step, spec, repo, builds)
    if prep.prepared(checkout, key):
        emit(f'  {repo.name}: its environment is current (key {key[:12]})')
        return 0
    said = submit(
        checkout, key, python=spec.python, root=spec.root, script=prep.job_script(spec, repo), kit=prep.kit_of(spec)
    )
    emit(f'  {repo.name}: not built for key {key[:12]}: {said}')
    return 0


def _artifacts(step: Step, spec: Deployment, _home: Path, repo: Repo) -> int:
    remote = declared_remote(checkout_of(spec, repo))
    if not remote:
        emit(f'  {repo.name}: no rclone artifact store declared')
        return 0
    why = probe(remote, rclone=step.tools.rclone)
    emit(f'  {repo.name}: ' + (f'WARNING {why}' if why else 'the rclone remote answers'), err=bool(why))
    return 0  # a warning, never a refusal: most parts declare no large outputs


def _femm(step: Step, spec: Deployment, path: Path, submit: prep.Submit) -> int:
    """Where the machine file at *path* declares ``[capabilities.femm]`` and FEMM 5 is not installed, ask its job.

    The build runs in a Slurm job (``hpcaccount femm-build``, :func:`femm_in_job`), never on the login node.
    """
    try:
        machine = machine_table(path) if path.is_file() else {}
    except Unreadable as broken:
        emit(f'  femm: refused -- {broken}', err=True)
        return 0
    if 'femm' not in machine.get('capabilities', {}):
        emit('  femm: not declared')
        return 0
    final = femm.install_dir(machinehome.tools())
    if final.is_dir():
        emit(f'  femm: {final} installed')
        return 0
    kit = checkout_of(spec, next(one for one in spec.repos if one.name == KIT))
    if step.dry:
        step.change(f'femm: its Slurm build job, into {final}', [])
        return 0
    script = f'cd {shlex.quote(str(kit))} && {shell_interpreter(".")} -m dev_lab.dev.hpcaccount femm-build'
    emit(f'  femm: {submit(kit, f"femm-{final.name}", python=spec.python, root=spec.root, script=script)}')
    return 0


def femm_in_job(home: Path, *, config: Path | None = None, tools: Tools | None = None) -> int:
    """The FEMM job's body, ON A COMPUTE NODE: build and install FEMM 5 where the machine file declares it."""
    path = config or config_path()
    step = Step(tools or Tools(), dry=False)
    try:
        spec = load(path)
        machine = machine_table(path) if path.is_file() else {}
        setup = grant_setup(path, step.read([*step.tools.id, '-un']).stdout.strip()) if machine else ()
    except (Unreadable, ValueError) as broken:
        emit(f'femm-build: refused -- {broken}', err=True)
        return 2
    if spec is None:
        emit(f'femm-build: refused -- {path} declares no [deploy]', err=True)
        return 2
    environment = tick_environment(home, spec.root, (), setup, spec.env)
    return femm.install(step, machine, environment=environment, tools_root=machinehome.tools(), home=home)


def _sound(url: str, subject: str, body: str) -> object:
    """One forge ``run`` alarm, raised by :mod:`dev_lab.dev.forgealarm` in a subprocess."""
    argv = [sys.executable, '-m', 'dev_lab.dev.forgealarm', 'run', url, subject, body]
    return _door.run(argv, capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)


def _report(spec: Deployment, refused: Refused, host: str, alarm: AlarmSink) -> int:
    """0 when every repo is deployed; else name each refusal, alarm its owner and return 2."""
    if not refused:
        return 0
    for repo in spec.repos:
        if why := refused.get(repo.name):
            alarm(repo.url, f'the deploy on {host} refused {repo.name}; it is not served there', why)
            emit(f'deploy refused {repo.name} (not served, no crontab line): {why}', err=True)
    emit(f'deploy finished for: {", ".join(r.name for r in _healthy(spec, refused)) or "no repo"}', err=True)
    return 2


def _admitted(args: argparse.Namespace, path: Path) -> tuple[Deployment, Mapping[str, Any]] | str:
    """The resolved declaration and its role's semantics, or why the deploy is refused before the host is asked."""
    try:
        spec = resolve(args, path)
    except Unreadable as broken:  # a hand-run deploy; a fleet deploy's render repaired the old shape before this
        return str(broken)
    if isinstance(spec, str):
        return spec
    semantics = {} if args.remove else account_role(spec.role, args.fleet_role, args.role_table)
    if isinstance(semantics, str):
        return semantics
    # CI-PAUSED gates the serving cron; a research deploy has none
    return (paused_refusal(spec.root) if semantics.get('serves', False) else '') or (spec, semantics)


def deploy(
    argv: Sequence[str],
    *,
    home: Path,
    hostname: str,
    tools: Tools | None = None,
    api: ApiCheck | None = None,
    role: RoleCheck | None = None,
    alarm: AlarmSink = _sound,
    submit: prep.Submit = prep.submit,
) -> int:
    """Run the deployment *argv* asks for; 0 done, 2 refused (the message names the remedy and refused repos)."""
    args = parser(__doc__.splitlines()[0]).parse_args(list(argv))
    path = args.config or config_path()
    admitted = _admitted(args, path)
    if isinstance(admitted, str):
        emit(f'deploy refused: {admitted}', err=True)
        return 2
    spec, semantics = admitted
    serves = bool(semantics.get('serves', False))
    short = hostname.split('.', 1)[0]
    emit(f'[host] account {os.environ.get("USER") or os.environ.get("USERNAME", "?")} on {short}')
    if why := host_refusal(spec, path, short, serves=serves, table=args.grant_table):
        emit(f'deploy refused: {why}', err=True)
        return 2
    path_env = os.pathsep.join([*tick_dirs(home)[:2], os.environ.get('PATH', '')])
    step = Step(tools or Tools(), dry=args.dry_run, path=path_env)
    if args.remove:
        emit('[cron] removing the marked lines')
        return crontab(step, [])
    slurm = slurm_dirs()
    if isinstance(slurm, str):
        emit(f'deploy refused: {slurm}', err=True)
        return 2
    refused: Refused = {}
    setup: list[str] = []  # the grant's setup lines: every tick runs inside them
    artifacts = '[artifacts] the rclone remote, where a repo declares one'
    every: dict[str, Callable[[], int]] = {
        'credentials': lambda: credentials(step, spec, home, api or auth_check, serves=serves),
        'reader': lambda: reader(spec, home, role or role_of, semantics=semantics),
        'grant': lambda: grant(step, path, args.grant_table),
        'store': lambda: store(step, spec, path),
        'runs': lambda: runs(step),
        'serve-git': lambda: _serve_git(step, home, path, slurm, setup, root=spec.root, env=spec.env),
        'headroom': lambda: headroom.check(step, spec, home),
        'checkouts': lambda: _each(step, spec, home, f'[checkouts] under {spec.root}', update, refused=refused),
        'login': lambda: login(step, home, spec.root),
        'prep': lambda: _each(
            step,
            spec,
            home,
            '[prep] each environment built for its inputs, else its Slurm prep job asked',
            lambda *a: _prep(*a, submit=submit),
            refused=refused,
        ),
        'artifacts': lambda: _each(step, spec, home, artifacts, _artifacts, refused=refused),
        'femm': lambda: _femm(step, spec, path, submit),
        'cron': lambda: _cron(step, spec, home, refused, serves=serves, slurm=slurm, setup=setup),
    }
    for name in phases_of(serves=serves):
        if rc := every[name]():
            return rc
    return _report(spec, refused, short, alarm)


def main(argv: Sequence[str]) -> int:
    """The CLI entry: this box's home and its fully qualified name (the grant's ssh host)."""
    return deploy(argv, home=Path.home(), hostname=socket.getfqdn())
