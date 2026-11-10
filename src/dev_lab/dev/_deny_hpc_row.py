"""The agent deny registry, HPC-THROUGH-THE-DOOR row -- pure DATA.

User ruling 2026-11-06: an agent never reaches an HPC login host or Slurm directly; heavy work goes through the
forge (VERDICTS-FROM-THE-FORGE), deploys through ``hpcaccount``. The night before, agents opened dozens of ssh
connections per diagnosis to the login nodes (six accounts, two hosts, poll loops with ``sleep``) and the cluster
stopped answering ssh.

HOW A HOST IS RECOGNISED, and why not by name. The declared hosts are the machine file's ``[[hpc.grant]] hosts``,
but the engine reads a COMMITTED ``deny-rules.json`` and cannot read the machine file at match time; rendering the
names into it would put fleet facts into git history, which user ruling 2026-10-23 forbids
(:mod:`dev_lab.dev.automode`). So the row matches the login-node SHAPE every declared grant host has -- a first
DNS label carrying ``login`` (``hpclogin01``, ``login2``) -- and ``sbatch``/``srun``/``salloc``/``scancel`` as a
command, or anywhere after ``ssh``. A non-HPC host (a workstation, a forge VM by address) is admitted.
"""

from __future__ import annotations

from dev_lab.dev.agentpolicy import exits_of
from dev_lab.dev.venvpath import PYTHON_SLOT

_ID = 'HPC-THROUGH-THE-DOOR'

__all__ = ['HPC_THROUGH_THE_DOOR']

_SLURM = r'(?:sbatch|srun|salloc|scancel)\b'
#: A login host as an ssh/scp/sftp/rsync target: ``[user@]<label with login>[.domain]`` ended by ``:``, ``/``, space.
_LOGIN_TARGET = r'[\s@][\w-]*[Ll][Oo][Gg][Ii][Nn][\w-]*(?:\.[\w.-]+)?(?=[\s:/"\x27]|$)'

HPC_THROUGH_THE_DOOR: dict[str, object] = {
    'id': _ID,
    'pattern': rf'(?:(?:ssh|scp|sftp|rsync)\b[^\n;&|]*?{_LOGIN_TARGET}|ssh\b[^\n]*?\b{_SLURM}|{_SLURM})',
    'matches': 'command',
    'hazard': 'an agent on an HPC login host or Slurm opens connections nobody budgets; a poll loop took the '
    "cluster's ssh down (2026-11-06).",
    'remedy': f'Status: the forge host card, {PYTHON_SLOT} -m dev_lab.dev.forge '
    f'{exits_of(_ID, "dev_lab.dev.forge")}; a cluster account: {PYTHON_SLOT} -m dev_lab.dev.hpcaccount '
    f'{exits_of(_ID, "dev_lab.dev.hpcaccount")} (deploy is run by the user on the account); tests: push and let the '
    'forge run them.',
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
    ),
}
