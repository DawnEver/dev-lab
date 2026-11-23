"""A DEPLOY NEVER STARTS WHAT CANNOT FIT (user ruling 2026-11-22) -- the deploy's ``[headroom]`` phase.

Measured that day: retention freed 70k files on an account at its file quota, the next deploy wrote ~140k (the uv
cache and seven venvs, 12-30k files each) and died at the hard limit, leaving half-built venvs, uv temp dirs and a
half-checked-out clone. So BEFORE any checkout or venv is written, this phase:

1. states the account's quota -- files AND bytes, each with its headroom (:func:`dev_lab.dev.quotawatch.lines`);
2. at the declared warning line (``[retention] pressure``) runs the account's own retention first, then re-reads;
3. refuses the deploy by name -- :data:`REFUSED`, the cause and the door -- when the file headroom left is below
   :func:`estimate`, the files the deploy may write. A refusal writes nothing, so nothing is left half-built.

The estimate is the worst case (every venv rebuilt, every missing checkout cloned): a venv costs what the repo's
CURRENT venv holds (counted, names only), else :data:`VENV_FILES`; a missing checkout costs :data:`CHECKOUT_FILES`.
"""

from __future__ import annotations

import shlex
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final

from lab_commons.hpc.layout import ROOT_VAR
from lab_commons.log import emit

from dev_lab.dev import quotawatch, venvpointer
from dev_lab.dev.diskusage import Usage, count_files, read_usage
from dev_lab.dev.hpcaccount.spec import Deployment, checkout_of
from dev_lab.dev.hpcaccount.steps import Step

__all__ = ['CHECKOUT_FILES', 'REFUSED', 'VENV_FILES', 'check', 'estimate']

#: A venv's files where the repo has none to count yet: the largest measured (2026-11-22: 12-30k each).
VENV_FILES: Final = 30_000
#: A fresh clone's files (working tree and ``.git``) where none exists yet to count.
CHECKOUT_FILES: Final = 20_000
#: The refusal's name.
REFUSED: Final = 'QUOTA-HEADROOM'

Reader = Callable[[Path], Usage | None]


def _read(home: Path) -> Usage | None:
    return read_usage(home, cluster=True)


def estimate(spec: Deployment) -> tuple[int, list[str]]:
    """The files this deploy may write at most, and one line per repo saying what it was priced from."""
    total, said = 0, []
    for repo in spec.repos:
        checkout = checkout_of(spec, repo)
        clone = 0 if (checkout / '.git').exists() else CHECKOUT_FILES
        live = venvpointer.current(checkout)
        venv = count_files(live) if live.is_dir() else VENV_FILES
        source = f'measured from {live}' if live.is_dir() else 'the prior, no venv yet'
        total += clone + venv
        said.append(f'{repo.name}: venv {venv} files ({source}) + checkout {clone} files')
    return total, said


def _retention(step: Step, root: str) -> int:
    script = f'export {ROOT_VAR}={shlex.quote(root)} && {shlex.quote(sys.executable)} -m dev_lab.dev.retention'
    return step.change(
        'retention --cluster --apply: free files before writing', [*step.tools.sh, f'{script} --cluster --apply']
    )


def check(step: Step, spec: Deployment, home: Path, *, read: Reader = _read) -> int:
    """0 when the deploy fits the account's file headroom; 2 refused by name, nothing written."""
    emit("[headroom] the account's quota, before anything is written")
    policy = quotawatch.declared_lines()
    usage = read(home)
    for line in quotawatch.lines(usage, policy):
        emit(f'  {line}')
    if usage is None:
        return 0
    if quotawatch.judge(usage, policy).near and not step.dry:
        _retention(step, spec.root)
        usage = read(home) or usage
        for line in quotawatch.lines(usage, policy):
            emit(f'  after retention: {line}')
    need, priced = estimate(spec)
    left = usage.files_left
    for line in priced:
        emit(f'  {line}')
    if left is None or left >= need:
        emit(f'  fits: up to {need} files to write' + (f', {int(left)} left' if left is not None else ''))
        return 0
    emit(
        f'deploy refused: {REFUSED}: up to {need} files to write, {int(left)} left under the file quota; nothing was '
        f'written -- free files first: {quotawatch.DOOR}',
        err=True,
    )
    return 2
