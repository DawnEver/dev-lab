"""ONE CRON TICK of a served repo on a cluster account: ``python -m dev_lab.dev.hpcaccount tick <repo>``.

THE HOST REFRESHES AND SERVES (incident 2026-10-13): a repo served from its OWN venv cannot update
itself when the kit in that venv is too old to run -- the code that would update it is the code that
fails. So the cron line runs THIS, from the host's dev-lab checkout
(:func:`dev_lab.dev.hpcaccount.spec.tick_command`), and then THE HOST KIT's ``forge serve`` in the repo's
checkout (:func:`~dev_lab.dev.hpcaccount.spec.host_serve_argv`); the repo's venv only runs its producers. Every
step is the deploy's own and keyed (:func:`dev_lab.dev.hpcaccount.steps.update` and ``build``), so an
unchanged tick only fetches.

A NEED IS RE-ASSERTED EVERY TICK (Ada 2026-10-25: a tool the deploy proved was gone later, and every tick
claimed parts its build could not make). Each repo's declared ``needs`` is probed by the deploy's own
:func:`~dev_lab.dev.hpcaccount.checks.runs`, once per tool per tick, in the tick's own environment (the cron
line already set it up); a repo lacking one is released unserved -- nothing claimed -- and a ``needs``
alarm names the account and the tool.

ONLY A VERIFICATION ACCOUNT SERVES (user ruling 2026-11-06): a tick on an account whose ``[deploy] role`` is not
``"verification"`` -- a research account a stale cron line survived on -- refreshes, then refuses to serve, exit 2
naming the role; its own ``hpcaccount deploy`` removes the line (:func:`dev_lab.dev.hpcaccount.spec.ticked`).
"""

from __future__ import annotations

import getpass
import shutil
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from lab_commons.config import config_path
from lab_commons.hpc.declared import REFUSALS
from lab_commons.log import emit

from dev_lab.dev._dep_project import follow_pin
from dev_lab.dev.forgealarm import NEEDS, Alarm, sound
from dev_lab.dev.forgeclaim import this_machine, this_seat
from dev_lab.dev.forgefleet import serve_off
from dev_lab.dev.forgehosts import card_host, mark_held
from dev_lab.dev.forgeoutbox import unprompted_client
from dev_lab.dev.hpcaccount.checks import runs
from dev_lab.dev.hpcaccount.grantslice import RERENDER
from dev_lab.dev.hpcaccount.spec import (
    KIT,
    VERIFICATION,
    Deployment,
    Repo,
    checkout_of,
    host_serve_argv,
    load,
    served,
    serves_here,
)
from dev_lab.dev.hpcaccount.steps import Step, Tools, build, declared, update
from dev_lab.dev.hpcaccount.tickwall import WALL, Wall, within
from dev_lab.dev.lockcheck import uv_version
from dev_lab.dev.roles import Unbound
from dev_lab.dev.tickholder import Holder

__all__ = ['account', 'announce_held', 'follow_uv', 'tick']

_runs = runs


def account() -> str:
    """The cluster account this tick runs as."""
    return getpass.getuser()


def follow_uv(name: str) -> str:
    """On the kit's tick (the host checkout's one writer), move this account's uv to the pin; ``''`` once it is."""
    if name != KIT:
        return ''
    uv = shutil.which('uv')
    return follow_pin(uv, uv_version()) if uv else 'this account has no uv on PATH'


def _lacking(step: Step, needs: Iterable[str], probed: dict[str, bool]) -> list[str]:
    """Each of *needs* whose ``--version`` does not exit 0 here; a tool already probed this tick is not re-run."""
    for tool in needs:
        if tool not in probed:
            probed[tool] = _runs(step.tools.sh, ':', tool)
    return [tool for tool in needs if not probed[tool]]


def _refresh(step: Step, spec: Deployment, home: Path, repo: Repo, probed: dict[str, bool]) -> tuple[str, list[str]]:
    """Fetch and check out *repo*'s ref, re-assert its needs, then bring its venv in step; why not, and what lacks."""
    if rc := update(step, spec, home, repo):
        return f'its checkout update exited {rc}', []
    try:
        if lacking := _lacking(step, declared(checkout_of(spec, repo)).needs, probed):
            return f'{account()} lacks {", ".join(lacking)} (`--version` does not run in the tick environment)', lacking
        rc = build(step, spec, home, repo)
    except REFUSALS as why:
        return str(why), []
    return (f'its venv build exited {rc}' if rc else ''), []


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
    probed: dict[str, bool] | None = None,
    wall: Wall | None = None,
) -> int:
    """One cron tick of served repo *name*: THE HOST refreshes, then serves it with its own kit.

    Runs from the host's dev-lab checkout, never the repo's venv (incident 2026-10-13: a repo venv
    whose old ``forge serve`` exited 2 every tick could never run the code that would update it). *name*
    follows its declared ref and its venv is rebuilt where its inputs (its committed lock among them) moved
    (:func:`dev_lab.dev.hpcaccount.steps.build`); a repo that cannot is RELEASED this tick with its reason,
    exit 2, and is not served. A repo whose checkout declares no ``hpc`` producer is refreshed and not served.
    One lacking a declared need also sounds a ``needs`` *alarm*; *probed* is the
    tick's probe cache, shared by every repo one tick serves.

    With a *wall* (:mod:`dev_lab.dev.hpcaccount.tickwall`) each phase is named in the tick's holder record and the
    serve runs within what is left of it; a refresh that spent the whole wall serves nothing this tick.

    THE SHARED KIT HAS ONE WRITER: dev-lab always has a line, served or not, so ITS OWN tick (under its own
    ``flock``) is the only one that moves the host checkout; every other tick reads it. Measured 2026-10-19
    (Ada): every repo's tick also updated it, each under only its own repo's flock, and concurrent ticks
    collided on ``.git/index.lock``. Serving is the host kit's ``forge serve`` in the repo's
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
    if lagging := follow_uv(name):
        alarm(Alarm(NEEDS, repo.url, f'{account()} runs a uv that is not the pin', lagging, about='uv'))
    why, lacking = _refresh(step, spec, home, repo, {} if probed is None else probed)
    if lacking:
        alarm(Alarm(NEEDS, repo.url, f'{account()} lacks {", ".join(lacking)}: {name} is not served', why))
    if why:
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
