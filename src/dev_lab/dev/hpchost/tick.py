"""ONE CRON TICK of a served repo on a cluster account: ``python -m dev_lab.dev.hpchost tick <repo>``.

THE HOST REFRESHES AND SERVES (incident 2026-10-13): a repo served from its OWN venv cannot update
itself when the kit in that venv is too old to run -- the code that would update it is the code that
fails. So the cron line runs THIS, from the host's dev-lab checkout
(:func:`dev_lab.dev.hpchost.spec.tick_command`), and then THE HOST KIT's ``forge serve`` in the repo's
checkout (:func:`~dev_lab.dev.hpchost.spec.host_serve_argv`); the repo's venv only runs its producers. Every
step is the deploy's own and keyed (:func:`dev_lab.dev.hpchost.steps.update` and ``build``), so an
unchanged tick only fetches.

A NEED IS RE-ASSERTED EVERY TICK (Ada 2026-10-25: a tool the deploy proved was gone later, and every tick
claimed parts its build could not make). Each repo's declared ``needs`` is probed by the deploy's own
:func:`~dev_lab.dev.hpchost.checks.runs`, once per tool per tick, in the tick's own environment (the cron
line already set it up); a repo lacking one is released unserved -- nothing claimed -- and a ``needs``
alarm names the account and the tool.
"""

from __future__ import annotations

import getpass
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import lab_commons.launch as _door
from lab_commons.config import config_path
from lab_commons.hpc.declared import REFUSALS
from lab_commons.log import emit

from dev_lab.dev.forgealarm import NEEDS, Alarm, sound
from dev_lab.dev.forgefleet import serve_off
from dev_lab.dev.hpchost.checks import runs
from dev_lab.dev.hpchost.spec import Deployment, Repo, checkout_of, host_serve_argv, load
from dev_lab.dev.hpchost.steps import Step, Tools, build, declared, update

__all__ = ['account', 'tick']

_runs = runs


def account() -> str:
    """The cluster account this tick runs as."""
    return getpass.getuser()


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
        if lacking := _lacking(step, declared(checkout_of(spec, home, repo)).needs, probed):
            return f'{account()} lacks {", ".join(lacking)} (`--version` does not run in the tick environment)', lacking
        rc = build(step, spec, home, repo)
    except REFUSALS as why:
        return str(why), []
    return (f'its venv build exited {rc}' if rc else ''), []


def tick(
    name: str,
    *,
    home: Path,
    config: Path | None = None,
    tools: Tools | None = None,
    run: Callable[..., Any] = _door.run,
    alarm: Callable[[Alarm], object] = sound,
    probed: dict[str, bool] | None = None,
) -> int:
    """One cron tick of served repo *name*: THE HOST refreshes, then serves it with its own kit.

    Runs from the host's dev-lab checkout, never the repo's venv (incident 2026-10-13: a repo venv
    whose old ``forge serve`` exited 2 every tick could never run the code that would update it). *name*
    follows its declared ref and its venv is rebuilt where its inputs (its committed lock among them) moved
    (:func:`dev_lab.dev.hpchost.steps.build`); a repo that cannot is RELEASED this tick with its reason,
    exit 2, and is not served. A repo declared ``serve = false`` is refreshed and not served.
    One lacking a declared need also sounds a ``needs`` *alarm*; *probed* is the
    tick's probe cache, shared by every repo one tick serves.

    THE SHARED KIT HAS ONE WRITER: dev-lab always has a line, served or not, so ITS OWN tick (under its own
    ``flock``) is the only one that moves the host checkout; every other tick reads it. Measured 2026-10-19
    (Ada): every repo's tick also updated it, each under only its own repo's flock, and concurrent ticks
    collided on ``.git/index.lock``. Serving is the host kit's ``forge serve`` in the repo's
    checkout (:func:`~dev_lab.dev.hpchost.spec.host_serve_argv`), never the repo venv's.
    """
    spec = load(config or config_path())
    repo = next((one for one in spec.repos if one.name == name), None) if spec else None
    if spec is None or repo is None:
        emit(f'[tick] refused: {name} is not a served repo of [deploy] in {config or config_path()}', err=True)
        return 2
    step = Step(tools or Tools(), dry=False)
    why, lacking = _refresh(step, spec, home, repo, {} if probed is None else probed)
    if lacking:
        alarm(Alarm(NEEDS, repo.url, f'{account()} lacks {", ".join(lacking)}: {name} is not served', why))
    if why:
        emit(f'[tick] {name} released, not served this tick: {why}', err=True)
        return 2
    serve_off({one.name: one.serve for one in spec.repos}, account(), alarm=alarm, repo=repo.url)
    if not repo.serve:
        return 0  # checked out and fresh; this account does not serve its queue
    checkout = checkout_of(spec, home, repo)
    return run(host_serve_argv(), cwd=checkout, check=False).returncode
