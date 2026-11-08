"""THE HOST REFRESHES A SERVED CHECKOUT before that checkout's own ``forge serve`` runs -- never the repo's kit.

INCIDENT 2026-10-13: a workstation served each repo with the repo's OWN venv, and that venv held a
lab-commons whose ``forge serve`` required a retired flag, so it exited 2 every tick -- and the code that
would have updated it was the code that could not run. A repo's own stale kit cannot own its own update;
the host's kit does, from outside it (:func:`refresh`): fast-forward the clean checkout to its upstream
(:func:`follow`), then sync its venv through ``dep --bootstrap`` when :func:`dev_lab.dev.venvfollow.stale` says
its inputs moved (:func:`sync_venv`) -- so a failed sync is retried by the next tick, and an unchanged checkout
costs one hash.

Shared by ``workstation deploy`` (its checkout and venv steps) and ``workstation serve`` (every tick).
A cluster account's tick is the same rule through its own keyed build (:func:`dev_lab.dev.hpcaccount.tick.tick`).
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import lab_commons.launch as _door
from lab_commons.log import emit

from dev_lab.dev.hpcaccount.steps import Step
from dev_lab.dev.netverb import run_network_verb
from dev_lab.dev.venvfollow import stale, stamp

__all__ = [
    'Moved',
    'follow',
    'network',
    'read',
    'refresh',
    'sync_venv',
]


def read(argv: Sequence[str], env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """A READ-ONLY call, also under ``--dry-run``; its output is never echoed."""
    return _door.run(
        argv, capture_output=True, text=True, encoding='utf-8', errors='replace', check=False,
        stdin=subprocess.DEVNULL, env={**os.environ, **(env or {})},
    )  # fmt: skip


@dataclass(frozen=True)
class Moved:
    """A checkout step's outcome: its exit, and why it was refused."""

    rc: int
    why: str = ''


def follow(step: Step, git: Sequence[str], checkout: Path) -> Moved:
    """Fast-forward an existing CLEAN *checkout* to its upstream; a dirty one is refused, never touched."""
    here = [*git, '-C', str(checkout)]
    if read([*here, 'status', '--porcelain']).stdout.strip():
        return Moved(2, why=f'{checkout} has local changes; commit or clean them, then re-run')
    if step.dry:
        return Moved(step.change(f'{checkout.name}: git fetch, then fast-forward to its upstream when behind', []))
    return _fast_forward(step, here, checkout.name)


def network(step: Step, what: str, argv: Sequence[str]) -> Moved:
    """A CHANGING network *argv* through the retry door (NETWORK-RETRY-THEN-REPORT); its remedy when it fails."""
    emit(f'  {what}')
    env = {**os.environ, **({'PATH': step.path} if step.path else {})}
    report = run_network_verb(argv, env=env)
    return Moved(0) if report.ok else Moved(report.returncode or 1, why=report.remedy)


def _fast_forward(step: Step, git: Sequence[str], name: str) -> Moved:
    if (fetched := network(step, f'{name}: git fetch', [*git, 'fetch', '-q'])).rc:
        return fetched
    head, upstream = (read([*git, 'rev-parse', rev]).stdout.strip() for rev in ('HEAD', '@{u}'))
    if not upstream:
        return Moved(2, why=f'{name} tracks no upstream; `git branch -u origin/<ref>` in it, then re-run')
    if head == upstream:
        emit(f'  {name}: current at {head[:12]}')
        return Moved(0)
    merge = [*git, 'merge', '--ff-only', '-q', '@{u}']
    rc = step.change(f'{name}: fast-forward {head[:12]} -> {upstream[:12]}', merge)
    return Moved(rc, why=f'cannot fast-forward {head[:12]} -> {upstream[:12]} (exit {rc})' if rc else '')


def sync_venv(step: Step, bootstrap: Sequence[str], checkout: Path) -> int:
    """Sync *checkout*'s venv when :func:`dev_lab.dev.venvfollow.stale`; the stamp only after it succeeded."""
    key = stale(checkout)
    if key is None:
        emit(f'  {checkout.name}: .venv current')
        return 0
    # The door's own rule: a primary checkout's environment moves only from that checkout.
    what = f'{checkout.name}: -m dev_lab.dev.dep --bootstrap {checkout}'
    if (rc := step.change(what, [*bootstrap, str(checkout)], cwd=checkout)) or step.dry:
        return rc
    stamp(checkout, key)
    return 0


def refresh(step: Step, *, git: Sequence[str], bootstrap: Sequence[str], checkout: Path) -> str:
    """Bring a served *checkout* to its upstream and its venv in step with it; ``''``, else why it cannot be.

    THE HOST OWNS THIS, never the repo's own kit (incident 2026-10-13): a venv holding a kit too old to
    run its own ``forge serve`` can never update itself, so the host moves it before invoking it.
    """
    if not (checkout / '.git').exists():
        return f'no checkout at {checkout}; re-run `workstation deploy`'
    if (moved := follow(step, git, checkout)).rc:
        return moved.why or f'its checkout exited {moved.rc}'
    if rc := sync_venv(step, bootstrap, checkout):
        return f'its venv sync exited {rc}'
    return ''
