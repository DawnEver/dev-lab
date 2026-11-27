"""THE PREP JOB DOOR: a served repo's environment is built in a Slurm job, never on the login node.

ONE-LOGIN-POLLER (user ruling 2026-11-27): the login node runs one cron poller per account, and its tick does only
git fetch, the forge, claims, ``sbatch``/``squeue``/``sacct``/``scancel``, reading what jobs wrote and deciding
merges. All CPU work -- the venv install, the native build, the ``needs`` probes, moving uv to its pin -- runs in a
Slurm job (measured 2026-11-27: Ada compute nodes reach HTTPS, so downloads too).

So a tick whose repo's inputs (its committed lock among them) moved does not build: it asks :func:`submit` for a
PREP JOB that builds the environment the key names, and serves that repo only once :func:`prepared` reads an
environment stamped with the current key (:data:`~dev_lab.dev.hpcaccount.steps.STAMP`, the deploy's own stamp,
:func:`~dev_lab.dev.hpcaccount.steps.env_key`).

WHAT THE JOB RUNS is this kit's own verb, ``python -m dev_lab.dev.hpcaccount prep-build <repo>``
(:func:`dev_lab.dev.hpcaccount.tick.prep_build`, the line :func:`job_script` writes): uv to its pin, the repo's
``needs`` probed, then :func:`~dev_lab.dev.hpcaccount.steps.build` -- built beside the live env and published only
once it succeeded, so the stamp moves last. The job SUBMISSION is lab-commons' (``lab_commons.hpc.prep``); the
interface needed, by name:

    ``submit_env_prep(checkout: Path, key: str, *, python: str, root: str, script: str) -> str``

submits *script* (a POSIX shell line) as one Slurm job of the account's grant, keyed by *key*: it never queues a
second job for a key already queued or running, and returns one line saying what it did -- ``submitted job <id>``,
``job <id> already queued for <key>``, ``job <id> failed: <log path>`` -- never raising for a job's failure. A
lab-commons without it is refused by name (:data:`ABSENT`), the repo unserved.
"""

from __future__ import annotations

import importlib
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Final

from dev_lab.dev import venvpointer
from dev_lab.dev.hpcaccount.spec import KIT, Deployment, Repo, checkout_of
from dev_lab.dev.hpcaccount.steps import STAMP

__all__ = ['ABSENT', 'Submit', 'job_script', 'prepared', 'submit']

#: ``(checkout, key, python=, root=, script=) -> one line``: submit (or find in flight) the prep job of *key*.
type Submit = Callable[..., str]

# TODO(arch-prep-job): lab-commons lane pr/toolchain/arch-prep-job provides submit_env_prep  # noqa: FIX002, TD003
# Until it lands, every repo whose environment is not current is refused by ABSENT, never built here.
_MODULE: Final = 'lab_commons.hpc.prep'
_FUNCTION: Final = 'submit_env_prep'
ABSENT: Final = (
    f"{_MODULE}.{_FUNCTION} is absent from this kit's lab-commons: a login-node tick never builds "
    '(ONE-LOGIN-POLLER), so this repo waits for the prep job -- update the kit to a lab-commons that provides it '
    '(lane pr/toolchain/arch-prep-job)'
)


def prepared(checkout: Path, key: str) -> bool:
    """Whether *checkout*'s live environment is stamped with *key* (built for the current inputs)."""
    stamp = venvpointer.current(checkout) / STAMP
    return stamp.is_file() and stamp.read_text(encoding='utf-8') == key


def job_script(spec: Deployment, repo: Repo) -> str:
    """The shell line a prep job runs: this kit's ``prep-build`` of *repo*, from the kit checkout."""
    kit = checkout_of(spec, next(one for one in spec.repos if one.name == KIT))
    python = venvpointer.shell_interpreter('.')
    return f'cd {shlex.quote(str(kit))} && {python} -m dev_lab.dev.hpcaccount prep-build {shlex.quote(repo.name)}'


def submit(checkout: Path, key: str, *, python: str, root: str, script: str) -> str:
    """lab-commons' prep job for *key*, as one line; :data:`ABSENT` when this kit's lab-commons has none."""
    try:
        door = getattr(importlib.import_module(_MODULE), _FUNCTION)
    except ImportError, AttributeError:
        return ABSENT
    return str(door(checkout, key, python=python, root=root, script=script))
