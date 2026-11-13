"""The agent deny registry, HPC-THROUGH-THE-DOOR row -- pure DATA.

User ruling 2026-11-06: an agent never reaches an HPC login host or Slurm directly; heavy work goes through the
forge (VERDICTS-FROM-THE-FORGE), deploys through ``hpcaccount``. The night before, agents opened dozens of ssh
connections per diagnosis to the login nodes (six accounts, two hosts, poll loops with ``sleep``) and the cluster
stopped answering ssh.

HOW A HOST IS RECOGNISED, and why not by name. The declared hosts are the machine file's
``[hpc.clusters.<name>] hosts``, but the engine reads a COMMITTED ``deny-rules.json`` and cannot read the machine
file at match time; rendering the names into it would put fleet facts into git history, which user ruling 2026-10-23
forbids (:mod:`dev_lab.dev.automode`). So the row matches the login-node SHAPE every declared cluster host has --
a first DNS label carrying ``login`` (``hpclogin01``, ``login2``) -- and ``sbatch``/``srun``/``salloc``/``scancel`` as a
command, or anywhere after ``ssh``. A non-HPC host (a workstation, a forge VM by address) is admitted.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final

from dev_lab.dev.agentpolicy import POLICY
from dev_lab.dev.venvpath import PYTHON_SLOT

_ID = 'HPC-THROUGH-THE-DOOR'

__all__ = ['CAMPAIGN', 'HPC_THROUGH_THE_DOOR', 'USAGES', 'exits', 'remedy']

#: The doors that are no :data:`POLICY` row of this table but are this row's exits all the same: the research batch
#: door lives in lab-commons, whose CLI is its own (``python -m lab_commons.hpc --help``).
#: They are KEY-ONLY: a key-only host (Ada, user ruling 2026-11-11) never needs a code, so every agent publishes,
#: gathers and cleans through them with no session held.
_BATCH: Final = ('plan', 'submit', 'status', 'gather', 'retry')
_RUN: Final = (('run', 'submit'), ('run', 'gather'), ('run', 'build'))
CAMPAIGN: Final[tuple[tuple[str, ...], ...]] = (
    *(('lab_commons.hpc', verb) for verb in _BATCH),
    *(('lab_commons.hpc', *verbs) for verbs in _RUN),
    ('lab_commons.hpc', 'clean'),
)

#: Per PURPOSE: the door exits (argv after ``python -m``) serving it, and their command shape. EVERY exit must be
#: under one (:func:`remedy` raises otherwise), so the refusal names every door by purpose (user ruling 2026-11-11);
#: the flags beyond the shape live in ``docs-src/dev/refusals.md#hpc-through-the-door``.
USAGES: Final[Mapping[str, tuple[tuple[tuple[str, ...], ...], str]]] = {
    'TOTP host': (
        (('dev_lab.dev.sshhold', 'open'), ('dev_lab.dev.sshhold', 'run')),
        '`sshhold open|run --code` (key-only: no code)',
    ),
    'deploy': (
        (
            ('dev_lab.dev.hpcaccount', 'deploy-fleet'),
            ('dev_lab.dev.hpcaccount', 'forget'),
            ('dev_lab.dev.hpcaccount', 'credential'),
            ('dev_lab.dev.hpcaccount', 'deploy'),
        ),
        '`hpcaccount deploy*|forget|credential`',
    ),
    'verify: push,': (
        (('dev_lab.dev.forge', 'queue'), ('dev_lab.dev.forge', 'run', 'show')),
        '`forge queue|run show <sha>`',
    ),
    'batch': (
        CAMPAIGN[: len(_BATCH) + len(_RUN)],
        '`lab_commons.hpc plan|submit|status|gather|retry|run`',
    ),
    'clean': (
        (('lab_commons.hpc', 'clean'),),
        '`lab_commons.hpc clean`',
    ),
}


def exits() -> tuple[tuple[str, ...], ...]:
    """Every door of :data:`POLICY` that is this row's exit, as its argv after ``python -m``, then :data:`CAMPAIGN`."""
    policy = tuple(door.argv[2:] for door in POLICY if door.deny == _ID and door.argv[:2] == ('python', '-m'))
    return (*policy, *CAMPAIGN)


def remedy(exit_argvs: Iterable[tuple[str, ...]]) -> str:
    """The refusal's remedy: each purpose holding an exit of *exit_argvs*, with its shape; an unheld exit raises."""
    given = tuple(exit_argvs)
    held = {argv for argvs, _ in USAGES.values() for argv in argvs}
    for argv in given:
        if argv not in held:
            msg = f'{_ID} exit {argv} has no USAGES line: a refusal must name its full command'
            raise KeyError(msg)
    doors = '; '.join(f'{purpose} {shape}' for purpose, (argvs, shape) in USAGES.items() if set(argvs) & set(given))
    return f'Doors ({PYTHON_SLOT} -m dev_lab.dev.<door>): {doors}.'


_SLURM = r'(?:sbatch|srun|salloc|scancel)\b'
#: A login host as an ssh/scp/sftp/rsync target: ``[user@]<label with login>[.domain]`` ended by ``:``, ``/``, space.
_LOGIN_TARGET = r'[\s@][\w-]*[Ll][Oo][Gg][Ii][Nn][\w-]*(?:\.[\w.-]+)?(?=[\s:/"\x27]|$)'

HPC_THROUGH_THE_DOOR: dict[str, object] = {
    'id': _ID,
    'pattern': rf'(?:(?:ssh|scp|sftp|rsync)\b[^\n;&|]*?{_LOGIN_TARGET}|ssh\b[^\n]*?\b{_SLURM}|{_SLURM})',
    'matches': 'command',
    'hazard': 'an agent on an HPC login host or Slurm opens connections nobody budgets; a poll loop took the '
    "cluster's ssh down (2026-11-06).",
    'remedy': remedy(exits()),
    'needs': None,
    'refuses': (
        'ssh alice@hpclogin01.example.org ls',
        'scp f alice@hpclogin02.example.org:',
        'rsync -a out/ login2.example.org:/scratch/out/',
        'sbatch job.sh',
        'scancel 4242',
        "ssh x@h 'sbatch j'",
    ),
    'permits': (
        'ssh ubuntu@203.0.113.10 uptime',
        'scp ubuntu@forge-vm:/srv/out.csv output/',
        'echo "ssh alice@hpclogin01 then sbatch job.sh"',
        'git commit -m "sbatch goes through the forge"',
        'python -m dev_lab.dev.forge queue',
        'python -m lab_commons.hpc clean --root /gpfs01/home/alice/out --at alice@hpclogin01.example.org e69',
        'python -m lab_commons.hpc gather -c job.toml --wait',
        'python -m lab_commons.hpc run submit --sha 0123abc',
    ),
}
