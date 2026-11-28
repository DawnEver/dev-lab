"""ONE CRON TICK of the served repos on a cluster account: ``python -m dev_lab.dev.hpcaccount tick <repo>...``.

THE HOST REFRESHES AND SERVES (incident 2026-10-13): a repo served from its OWN venv cannot update
itself when the kit in that venv is too old to run -- the code that would update it is the code that
fails. So the cron line runs THIS, from the host's dev-lab checkout
(:func:`dev_lab.dev.hpcaccount.spec.tick_command`), and then THE HOST KIT's ``forge serve`` in the repo's
checkout (:func:`~dev_lab.dev.hpcaccount.spec.host_serve_argv`); the repo's venv only runs its producers.

THE TICK NEVER BUILDS (ONE-LOGIN-POLLER, user ruling 2026-11-27): a login node runs one poller per account, and
its tick does only git fetch, the forge, claims, Slurm's ``sbatch``/``squeue``/``sacct``/``scancel`` and reading
what jobs wrote. So it fetches and checks out each repo (:func:`dev_lab.dev.hpcaccount.steps.update`), reads the
key of its environment (:func:`~dev_lab.dev.hpcaccount.steps.env_key`, its committed lock among the inputs) and
serves it only when the live environment is stamped with that key (:func:`dev_lab.dev.hpcaccount.prep.prepared`).
A key that moved asks the PREP JOB for it (:func:`dev_lab.dev.hpcaccount.prep.submit`: the venv install, the
native build, the ``needs`` probes and uv's pin all run there) and releases the repo unserved this tick, naming
the key and what the job door said.

ONLY A VERIFICATION ACCOUNT SERVES (user ruling 2026-11-06): a tick on an account whose ``[deploy] role`` is not
``"verification"`` -- a research account a stale cron line survived on -- refreshes, then refuses to serve, exit 2
naming the role; its own ``hpcaccount deploy`` removes the line (:func:`dev_lab.dev.hpcaccount.spec.ticked`).
"""

from __future__ import annotations

import getpass
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lab_commons.config import config_path
from lab_commons.hpc.declared import REFUSALS
from lab_commons.log import emit

from dev_lab.dev.forgealarm import Alarm, sound
from dev_lab.dev.forgeclaim import this_machine, this_seat
from dev_lab.dev.forgefleet import serve_off
from dev_lab.dev.forgehosts import card_host, mark_held
from dev_lab.dev.forgeoutbox import unprompted_client
from dev_lab.dev.hpcaccount import prep
from dev_lab.dev.hpcaccount.checks import ALWAYS, PINNED_RUST, follow_uv, runs, tool_plan
from dev_lab.dev.hpcaccount.grantslice import RERENDER
from dev_lab.dev.hpcaccount.spec import (
    VERIFICATION,
    Deployment,
    Repo,
    checkout_of,
    host_serve_argv,
    load,
    served,
    serves_here,
    uv_cache,
)
from dev_lab.dev.hpcaccount.steps import Step, Tools, build, declared, env_key, prune_uv, update
from dev_lab.dev.hpcaccount.tickwall import WALL, Wall, within
from dev_lab.dev.lockcheck import TOOLCHAIN
from dev_lab.dev.roles import Unbound
from dev_lab.dev.tickholder import Holder

__all__ = ['account', 'announce_held', 'prep_build', 'tick']


def account() -> str:
    """The cluster account this tick runs as."""
    return getpass.getuser()


def _refresh(step: Step, spec: Deployment, home: Path, repo: Repo, submit: prep.Submit) -> str:
    """Fetch and check out *repo*'s ref, then serve only an environment built for its inputs; else why not.

    Nothing is built here (ONE-LOGIN-POLLER): an environment whose key moved is asked of the prep job.
    """
    if rc := update(step, spec, home, repo):
        return f'its checkout update exited {rc}'
    checkout = checkout_of(spec, repo)
    try:
        builds = declared(checkout)
        if not builds.install:
            return 'it declares no [tool.lab_commons.hpc] install'
        key = env_key(step, spec, repo, builds)
    except REFUSALS as why:
        return str(why)
    if prep.prepared(checkout, key):
        return ''
    said = submit(checkout, key, python=spec.python, root=spec.root, script=prep.job_script(spec, repo))
    return f'its environment is not yet built for key {key[:12]} -- a Slurm prep job builds it, never the tick: {said}'


_runs = runs


def prep_build(name: str, *, home: Path, config: Path | None = None, tools: Tools | None = None) -> int:
    """The prep job's body, ON A COMPUTE NODE: uv to its pin, *name*'s tools, its environment, the uv cache pruned.

    The tools are ``uv``, ``rclone`` and the repo's ``needs``, each probed by its ``--version`` IN THE CHECKOUT on the
    node (so its ``rust-toolchain.toml`` applies) and one that does not run installed through its one installer
    (:func:`~dev_lab.dev.hpcaccount.checks.tool_plan`), else refused by name. A ``cargo`` need of a checkout pinning
    its toolchain gets that toolchain (``rustup toolchain install`` reads the pin). Every tool is probed again after
    the installs; then :func:`~dev_lab.dev.hpcaccount.steps.build`, the needs stamped as proven
    (:func:`~dev_lab.dev.hpcaccount.prep.stamp_tools`, what admits a part needing them) and the account's ONE uv cache
    pruned. 0 built (or already current); 2 refused, the reason printed -- the job's log is what the tick's next
    submit names.
    """
    path = config or config_path()
    try:
        spec = load(path)
    except ValueError as refused:
        emit(f'[prep-build] refused: {refused}', err=True)
        return 2
    repo = next((one for one in spec.repos if one.name == name), None) if spec else None
    if spec is None or repo is None:
        emit(f'[prep-build] refused: {name} is not a repo of [deploy] in {path}', err=True)
        return 2
    step = Step(tools or Tools(), dry=False)
    if lagging := follow_uv():
        emit(f'[prep-build] {lagging}', err=True)
    checkout = checkout_of(spec, repo)
    here = f'cd {shlex.quote(str(checkout))}'  # a pinned toolchain applies in its checkout
    try:
        needs = declared(checkout).needs
        installs, uninstallable = tool_plan(needs, found=lambda tool: _runs(step.tools.sh, here, tool))
        cache = {'UV_CACHE_DIR': str(uv_cache(spec.root))}  # `uv tool install`: the ONE cache, not the user default
        for tool, script in installs:
            step.change(f'install {tool}: {script}', [*step.tools.sh, script], env=cache)
        if 'cargo' in needs and (checkout / TOOLCHAIN).is_file():
            step.change(f'install the toolchain {TOOLCHAIN} pins', [*step.tools.sh, f'{here} && {PINNED_RUST}'])
        if lacking := [tool for tool in dict.fromkeys([*ALWAYS, *needs]) if not _runs(step.tools.sh, here, tool)]:
            none = f' ({", ".join(uninstallable)} has no installer)' if uninstallable else ''
            emit(
                f'[prep-build] {name}: this node lacks {", ".join(lacking)}{none} -- ask for it on the compute nodes, '
                'or link it into ~/.local/bin; the next tick asks again',
                err=True,
            )
            return 2
        rc = build(step, spec, home, repo)
    except REFUSALS as why:
        emit(f'[prep-build] {name} refused: {why}', err=True)
        return 2
    if rc:
        return rc
    prep.stamp_tools(checkout, needs)
    return prune_uv(step, spec)


def _declared(name: str, path: Path) -> tuple[Deployment, Repo] | str:
    """The deployment *path* declares and its repo *name*; else why this tick has none -- named, never a traceback."""
    try:
        spec = load(path)
    except ValueError as refused:
        return str(refused)
    repo = next((one for one in spec.repos if one.name == name), None) if spec else None
    if spec is None or repo is None:
        return f'{name} is not a served repo of [deploy] in {path}'
    return spec, repo


def _ours(spec: Deployment, repo: Repo) -> bool | str:
    """Whether this account serves *repo*; else why the family's binding cannot be read."""
    try:
        return serves_here(spec, repo)
    except Unbound as undeclared:
        return str(undeclared)
    except ValueError as refused:  # the layered reader's own refusal (lab_commons.config.section)
        return f'{refused} -- {RERENDER}'


def tick(
    name: str,
    *,
    home: Path,
    config: Path | None = None,
    tools: Tools | None = None,
    run: Callable[..., Any] = within,
    alarm: Callable[[Alarm], object] = sound,
    submit: prep.Submit = prep.submit,
    wall: Wall | None = None,
) -> int:
    """One cron tick of served repo *name*: THE HOST refreshes, then serves it with its own kit.

    Runs from the host's dev-lab checkout, never the repo's venv (incident 2026-10-13: a repo venv
    whose old ``forge serve`` exited 2 every tick could never run the code that would update it). *name*
    follows its declared ref and is served only from an environment built for its inputs (its committed lock among
    them); one whose inputs moved is asked of the prep job (*submit*, :func:`dev_lab.dev.hpcaccount.prep.submit`)
    and RELEASED this tick with its reason, exit 2, as is a repo that cannot be refreshed. A repo whose checkout
    declares no ``hpc`` producer is refreshed and not served.

    With a *wall* (:mod:`dev_lab.dev.hpcaccount.tickwall`) each phase is named in the tick's holder record and the
    serve runs within what is left of it; a refresh that spent the whole wall serves nothing this tick.

    THE SHARED KIT HAS ONE WRITER: only the kit's own refresh moves the host checkout, and the account's one tick
    holds the one lock (ONE-LOGIN-POLLER); every other repo's refresh reads it. Measured 2026-10-19 (Ada): every
    repo's tick also updated it, each under only its own repo's flock, and concurrent ticks collided on
    ``.git/index.lock``. Serving is the host kit's ``forge serve`` in the repo's
    checkout (:func:`~dev_lab.dev.hpcaccount.spec.host_serve_argv`), never the repo venv's.
    """
    found = _declared(name, config or config_path())
    if isinstance(found, str):
        emit(f'[tick] refused: {found}', err=True)
        return 2
    spec, repo = found
    step = Step(tools or Tools(), dry=False)
    if wall is not None:
        wall.phase(f'refreshing {name}')
    if why := _refresh(step, spec, home, repo, submit):
        emit(f'[tick] {name} released, not served this tick: {why}', err=True)
        return 2
    if spec.role != VERIFICATION:
        role = spec.role or 'undeclared'
        emit(f'[tick] {name} refused to serve: [deploy] role is {role}; only a {VERIFICATION} account serves', err=True)
        return 2
    ours = _ours(spec, repo)
    if isinstance(ours, str):
        emit(f'[tick] {name} released, not served this tick: {ours}', err=True)
        return 2
    here = served(spec)
    serve_off({one.name: one.name in here for one in spec.repos}, account(), alarm=alarm, repo=repo.url)
    if not ours:
        return 0  # checked out and fresh; its producer is not the HPC, so this account never serves its queue
    return _serve(name, checkout_of(spec, repo), run, wall)


def _serve(name: str, checkout: Path, run: Callable[..., Any], wall: Wall | None) -> int:
    """The host kit's ``forge serve`` in *checkout*, within what is left of *wall*; nothing when it is spent."""
    if wall is not None:
        if not wall.left():
            emit(wall.ended('ended at its wall'), err=True)
            return WALL
        wall.phase(f'serving {name}')
    return run(host_serve_argv(), cwd=checkout, check=False, wall=wall).returncode


def announce_held(
    name: str,
    holder: Holder,
    *,
    config: Path | None = None,
    mark: Callable[[Path, str, dict[str, Any]], str] = lambda checkout, host, held: mark_held(
        unprompted_client(checkout), host, held
    ),
) -> str:
    """Publish on *name*'s host card that its tick is held by *holder*; what happened, as one line.

    The card's ``ticked`` stays the holder's last, so ``forge queue`` reads ``tick held <age> in <phase>`` where it
    guessed STALE (measured 2026-11-23). A forge that cannot be reached is said, never fatal: the cron log has the line.
    """
    found = _declared(name, config or config_path())
    if isinstance(found, str):
        return f'[tick] {name}: the held card was not published: {found}'
    spec, repo = found
    held = {'pid': holder.pid, 'since': holder.since, 'phase': holder.phase}
    try:
        done = mark(checkout_of(spec, repo), card_host(this_machine(), this_seat()), held)
    except (OSError, RuntimeError, ValueError) as failed:  # ForgeCallFailed and NoCredential among them
        return f'[tick] {name}: the held card was not published: {failed}'
    return f'[tick] {name}: host card marked held ({done})'
