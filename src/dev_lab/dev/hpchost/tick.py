"""ONE CRON TICK of a served repo on a cluster account: ``python -m dev_lab.dev.hpchost tick <repo>``.

THE HOST REFRESHES AND SERVES (incident 2026-10-13): a repo served from its OWN venv cannot update
itself when the kit in that venv is too old to run -- the code that would update it is the code that
fails. So the cron line runs THIS, from the host's dev-lab checkout
(:func:`dev_lab.dev.hpchost.spec.tick_command`), and then THE HOST KIT's ``forge serve`` in the repo's
checkout (:func:`~dev_lab.dev.hpchost.spec.host_serve_argv`); the repo's venv only runs its producers. Every
step is the deploy's own and keyed (:func:`dev_lab.dev.hpchost.steps.update` and ``build``), so an
unchanged tick only fetches.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import lab_commons.launch as _door
from lab_commons.config import config_path
from lab_commons.hpc.declared import REFUSALS
from lab_commons.log import emit

from dev_lab.dev.hpchost.spec import Deployment, Repo, checkout_of, host_serve_argv, load
from dev_lab.dev.hpchost.steps import Step, Tools, build, update

__all__ = ['tick']


def _refresh(step: Step, spec: Deployment, home: Path, repo: Repo) -> str:
    """Fetch and check out *repo*'s ref, then bring its venv in step (each build skipped while its key holds)."""
    if rc := update(step, spec, home, repo):
        return f'its checkout update exited {rc}'
    try:
        rc = build(step, spec, home, repo)
    except REFUSALS as why:
        return str(why)
    return f'its venv build exited {rc}' if rc else ''


def tick(
    name: str,
    *,
    home: Path,
    config: Path | None = None,
    tools: Tools | None = None,
    run: Callable[..., Any] = _door.run,
) -> int:
    """One cron tick of served repo *name*: THE HOST refreshes, then serves it with its own kit.

    Runs from the host's dev-lab checkout, never the repo's venv (incident 2026-10-13: a repo venv
    whose old ``forge serve`` exited 2 every tick could never run the code that would update it). *name*
    follows its declared ref and its venv is rebuilt where its inputs (its committed lock among them) moved
    (:func:`dev_lab.dev.hpchost.steps.build`); a repo that cannot is RELEASED this tick with its reason,
    exit 2, and is not served.

    THE SHARED KIT HAS ONE WRITER: dev-lab is always a served repo, so ITS OWN tick (under its own
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
    if why := _refresh(step, spec, home, repo):
        emit(f'[tick] {name} released, not served this tick: {why}', err=True)
        return 2
    checkout = checkout_of(spec, home, repo)
    return run(host_serve_argv(), cwd=checkout, check=False).returncode
