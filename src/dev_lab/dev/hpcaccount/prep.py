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
``needs`` installed and probed, then :func:`~dev_lab.dev.hpcaccount.steps.build` -- built beside the live env and
published only once it succeeded, so the stamp moves last.

THE TOOLS STAMP (:data:`TOOLS`) is how a need proven on a compute node reaches ADMISSION. The prep job writes, into the
live environment beside its key stamp, each declared ``need`` whose ``--version`` ran on the node in the checkout (so a
``rust-toolchain.toml`` pin applies); the serve's Slurm supply (:meth:`dev_lab.dev.forgeslurm.SlurmCluster.standing`)
lists them as present (:func:`proven`). Measured 2026-11-28 (Ada, ezxmw9): every v1 ``cargo`` part waited
``not admitted: lacking cargo`` -- an account's supply named no tool a probe on the login node could not see, and that
node never runs one. An environment without the stamp is not :func:`prepared`, so the next tick asks the job again.

The job SUBMISSION is lab-commons' (``lab_commons.hpc.prep``); the
interface needed, by name:

    ``submit_env_prep(checkout: Path, key: str, *, python: str, root: str, script: str, kit: str, retry: bool)``

submits *script* (a POSIX shell line) as one Slurm job of the account's grant, keyed by *key*: it never queues a
second job for a key already queued or running, and returns one line saying what it did -- ``submitted job <id>``,
``job <id> already queued for <key>``, ``job <id> failed: <log path>`` -- never raising for a job's failure. A
lab-commons without it is refused by name (:data:`ABSENT`), the repo unserved.

A FAILED JOB IS NEVER A DEAD END (every-wall-teaches; measured 2026-11-28, Ada: a served repo's envprep jobs
failed ``Failed to build a native library through cargo`` before this kit installed cargo, and nothing could ever
retry them). *kit* is this kit's commit (:func:`kit_of`): a failure recorded under another kit predates what builds
the env now and is resubmitted once, naming why. A failure under this kit stays reported, and the line names its
door (:data:`RETRY`): ``hpcaccount prep-retry --account <user> <repo>`` (:mod:`~dev_lab.dev.hpcaccount.prepretry`)
resubmits once with *retry*.
"""

from __future__ import annotations

import getpass
import importlib
import shlex
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Final

from dev_lab.dev import venvpointer
from dev_lab.dev.forgestatus import head_sha
from dev_lab.dev.hpcaccount.spec import KIT, Deployment, Repo, checkout_of
from dev_lab.dev.hpcaccount.steps import STAMP

__all__ = ['ABSENT', 'RETRY', 'TOOLS', 'Submit', 'job_script', 'kit_of', 'prepared', 'proven', 'stamp_tools', 'submit']

#: ``(checkout, key, python=, root=, script=, kit=, retry=) -> one line``: submit (or find in flight) *key*'s prep job.
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


#: The door a failed prep job's line names: resubmit it once, from the workstation.
RETRY: Final = 'python -m dev_lab.dev.hpcaccount prep-retry --account {account} {repo}'


#: The live environment's list of the needs its prep job proved on a compute node, one per line.
TOOLS: Final = '.lab-prep-tools'


def prepared(checkout: Path, key: str) -> bool:
    """Whether *checkout*'s live environment is stamped with *key* and carries its prep job's :data:`TOOLS` stamp."""
    live = venvpointer.current(checkout)
    stamp = live / STAMP
    return stamp.is_file() and stamp.read_text(encoding='utf-8') == key and (live / TOOLS).is_file()


def stamp_tools(checkout: Path, tools: Iterable[str]) -> None:
    """Record *tools* as proven on a compute node in *checkout*'s live environment (the prep job, after its build)."""
    (venvpointer.current(checkout) / TOOLS).write_text(''.join(f'{tool}\n' for tool in sorted(set(tools))), 'utf-8')


def proven(checkout: Path) -> frozenset[str]:
    """The needs *checkout*'s prep job proved on a compute node; none before it stamped them; never probed."""
    stamp = venvpointer.current(checkout) / TOOLS
    if not stamp.is_file():
        return frozenset()
    return frozenset(line.strip() for line in stamp.read_text(encoding='utf-8').splitlines()) - {''}


def job_script(spec: Deployment, repo: Repo) -> str:
    """The shell line a prep job runs: this kit's ``prep-build`` of *repo*, from the kit checkout."""
    kit = checkout_of(spec, next(one for one in spec.repos if one.name == KIT))
    python = venvpointer.shell_interpreter('.')
    return f'cd {shlex.quote(str(kit))} && {python} -m dev_lab.dev.hpcaccount prep-build {shlex.quote(repo.name)}'


def kit_of(spec: Deployment) -> str:
    """The commit of *spec*'s kit checkout -- what builds every environment; a stable placeholder when unreadable."""
    kit = checkout_of(spec, next(one for one in spec.repos if one.name == KIT))
    return (head_sha(kit) if kit.is_dir() else None) or f'unreadable:{kit.as_posix()}'


def submit(checkout: Path, key: str, *, python: str, root: str, script: str, kit: str, retry: bool = False) -> str:
    """lab-commons' prep job for *key*, as one line; :data:`ABSENT` when this kit's lab-commons has none.

    A failed job's line names :data:`RETRY` for this account and *checkout*'s repo.
    """
    try:
        door = getattr(importlib.import_module(_MODULE), _FUNCTION)
    except ImportError, AttributeError:
        return ABSENT
    said = str(door(checkout, key, python=python, root=root, script=script, kit=kit, retry=retry))
    if said.startswith('job ') and ' failed: ' in said:
        said += ' -- once its cause is fixed, retry: ' + RETRY.format(account=getpass.getuser(), repo=checkout.name)
    return said
