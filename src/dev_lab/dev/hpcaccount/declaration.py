"""What an account's ``deploy`` DECLARES -- its flags, the stored ``[deploy]`` they must agree with, and the write.

Split from :mod:`~dev_lab.dev.hpcaccount.deploy` at the module-size band (2026-11-16): this module turns argv and
the machine file into one :class:`~dev_lab.dev.hpcaccount.spec.Deployment` (or the refusal naming its remedy), and
stores a first declaration; the deploy runs the steps.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from lab_commons.log import emit

from dev_lab.dev.hpcaccount.spec import (
    DEFAULT_PYTHON,
    KIT,
    Deployment,
    load,
    parse_repo,
    render,
    role_refusal,
)
from dev_lab.dev.hpcaccount.steps import Step

__all__ = ['declaration', 'parser', 'resolve', 'store']


def parser(deploy_doc: str = '') -> argparse.ArgumentParser:
    """The deploy's flags; *deploy_doc* is the command's one-line description."""
    parser = argparse.ArgumentParser(prog='dev_lab.dev.hpcaccount deploy', description=deploy_doc)
    parser.add_argument('--config', type=Path, help='the machine file holding [deploy] (default: lab_commons.config)')
    parser.add_argument('--host', help='declare: the one login host serving this account')
    parser.add_argument(
        '--repo', type=parse_repo, action='append', default=[], help='declare: <name>=<https url>@<branch>'
    )
    parser.add_argument(
        '--root', default='', help="declare: the account's absolute root (its cluster's [hpc.clusters.<c>] root)"
    )
    parser.add_argument('--python', default=DEFAULT_PYTHON, help='declare: the uv-managed interpreter request')
    parser.add_argument('--slurm-account', default='', help="declare: the grant's account, when Slurm names several")
    parser.add_argument('--partition', action='append', default=[], help='declare: a partition the grant may use')
    parser.add_argument('--role', default='', help='declare: the role name (verification serves; research never)')
    parser.add_argument('--fleet-role', default='', help="deploy-fleet: the workstation's role for this account")
    parser.add_argument('--role-table', type=json.loads, help="deploy-fleet: the role's [hpc.roles] table, JSON")
    parser.add_argument(
        '--grant-table', type=json.loads, help="deploy-fleet: this account's slice of the declared [hpc], JSON"
    )
    parser.add_argument('--dry-run', action='store_true', help='print every action; change nothing')
    parser.add_argument('--remove', action='store_true', help='delete the marked crontab lines only')
    return parser


def granted_root(table: Mapping[str, Any] | None) -> str:
    """The cluster root deploy-fleet's ``--grant-table`` declares (:func:`~dev_lab.dev.hpcaccount.fleet.grant_slice`).

    Measured 2026-11-20: every account file's rendered ``[deploy]`` names no root (the family's cluster holds it), so
    a deploy reading only the machine file refused "no root declared" on every account; the root it was handed is
    the family's own. ``''`` when the table names none.
    """
    clusters = (table or {}).get('clusters', {})
    return next((str(c['root']) for c in clusters.values() if isinstance(c, Mapping) and c.get('root')), '')


def declaration(args: argparse.Namespace, path: Path) -> Deployment | str:
    """The declared deployment (stored, else from the flags); a refusal is returned as its message."""
    stored = load(path, root=granted_root(args.grant_table))
    if not (args.host or args.repo):
        return stored or (
            f'no [deploy] in {path}: declare it once with --host <login host> --repo <name>=<https url>@<branch> ...'
        )
    if not (args.host and args.repo):
        return 'a declaration needs both --host and at least one --repo'
    fields = (args.host, args.root, args.python, tuple(args.repo), args.slurm_account, tuple(args.partition))
    given = Deployment(*fields, args.role)
    if stored is not None and stored != given:
        return (
            f'{path} already declares a different [deploy]: it is rendered from the account layer '
            'hosts/<cluster>-<user>.toml -- edit the layer in the config source, then run '
            'python -m dev_lab.dev.hpcaccount deploy-fleet --account <user> from the workstation (it renders the '
            'layer over this file); or run without --host/--repo'
        )
    return given


def resolve(args: argparse.Namespace, path: Path) -> Deployment | str:
    """The declared deployment, refused unless it declares its role and the kit (dev-lab), which every tick runs."""
    spec = declaration(args, path)
    if isinstance(spec, Deployment) and KIT not in {repo.name for repo in spec.repos}:
        return f'every tick runs {KIT}, so the host checks it out: add --repo {KIT}=<https url>@<branch>'
    if isinstance(spec, Deployment) and not args.remove and (why := role_refusal(spec, path)):
        return why  # a deploy never serves silently; --remove needs no role
    return spec


def store(step: Step, spec: Deployment, path: Path) -> int:
    """Store a first declaration once the host and every credential have passed."""
    if load(path, root=spec.root) is not None:
        return 0
    emit('[declare]')
    if step.dry:
        emit(f'  [dry-run] declare [deploy] in {path}')
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as out:
        out.write(render(spec))
    emit(f'  declared [deploy] in {path}')
    return 0
