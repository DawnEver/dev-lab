"""``ci-pause`` / ``ci-resume`` -- stop and restart a VERIFICATION account's forge CI cron around cluster maintenance.

Run ON the account; ``ci-pause-fleet`` / ``ci-resume-fleet`` start them
(:func:`dev_lab.dev.hpcaccount.accountset.main_fleet`) on the selected accounts whose ``[deploy] role`` serves; a
research account has no CI cron by design and is skipped, or refused when named by ``--account``.

``ci-pause --from <clone> --host <name> [--config <machine file>] [--dry-run] [--discard-drift]``: refuse a role that
does not serve. NOTHING IS BACKED UP -- the config source is the truth and the account its render (user ruling
2026-11-16) -- so the account's drift is computed first (:mod:`~dev_lab.dev.hpcaccount.drift`) and the pause REFUSES,
naming each item, while the account holds anything the config source cannot render: declare it there, or accept
its loss with ``--discard-drift``. Then it writes the CI-PAUSED marker (:mod:`~dev_lab.dev.hpcaccount.cimark`) and
removes ONLY this tool's marked crontab lines (:func:`~dev_lab.dev.hpcaccount.steps.crontab` with none), every other
line kept. Running jobs are never touched: this module runs no Slurm command at all.

``ci-resume [--config <machine file>] [--dry-run]``: refuse without the marker; rewrite the lines the deploy writes
from the account's declaration (:func:`~dev_lab.dev.hpcaccount.spec.cron_lines`, never a stale saved text), verify
``crontab -l`` holds each, and delete the marker.

``--credential <id> --cluster <name>`` (either verb): redeem a granted :data:`~dev_lab.dev.hpcaccount.cicron.ACTION`
credential whose subject is this cluster, this account (``id -un``) and the verb's direction, before any change; a
mismatched one refuses with nothing changed (:mod:`~dev_lab.dev.hpcaccount.cicron`). A dry run spends nothing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from collections.abc import Sequence
from pathlib import Path

from lab_commons.config import config_path
from lab_commons.log import emit

from dev_lab.dev.hpcaccount import cicron, deploy
from dev_lab.dev.hpcaccount.cimark import RESUME_DOOR, marker
from dev_lab.dev.hpcaccount.drift import DISCARD, account_drift, unrenderable
from dev_lab.dev.hpcaccount.grantslice import grant_setup
from dev_lab.dev.hpcaccount.spec import MARK, Deployment, cron_lines, load, ticked
from dev_lab.dev.hpcaccount.steps import Step, Tools, crontab

__all__ = ['ci_pause', 'ci_resume', 'main_pause', 'main_resume']


def _parser(verb: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f'dev_lab.dev.hpcaccount {verb}', description=__doc__.splitlines()[0])
    parser.add_argument('--config', type=Path, help='the rendered machine file (default: lab_commons.config)')
    parser.add_argument('--dry-run', action='store_true', help='print every action; change nothing')
    parser.add_argument(
        '--credential', help=f'the id of a granted {cicron.ACTION} credential, redeemed before a change'
    )
    parser.add_argument('--cluster', help="this account's cluster: the subject a --credential is redeemed for")
    return parser


def _consented(verb: str, step: Step, args: argparse.Namespace, redeem_with: cicron.Redeem | None) -> str | None:
    """``None`` when no credential is given or it is redeemed for this cluster and account; else the refusal."""
    if args.credential is None:
        return None
    if not args.cluster:
        return f'--credential needs --cluster: the subject names the cluster ({cicron.ACTION})'
    user = step.read([*step.tools.id, '-un']).stdout.strip()
    wanted = cicron.subject(verb, args.cluster, [user])
    return cicron.spend(args.credential, wanted, redeem_with=redeem_with)


def _serving(machine: Path) -> Deployment | str:
    spec = load(machine) if machine.is_file() else None
    if spec is None:
        return f'no [deploy] in {machine}: deploy it with python -m dev_lab.dev.hpcaccount deploy-fleet'
    if not ticked(spec):
        return f'its [deploy] role {spec.role!r} does not serve: no CI cron by design, nothing to pause'
    return spec


def _lost(step: Step, home: Path, machine: Path, args: argparse.Namespace) -> list[str] | str:
    """What the account would lose (accepted under ``--discard-drift``); else why the pause is refused."""
    found = account_drift(step, home, machine, args.clone.expanduser(), args.host)
    if isinstance(found, str):
        return f'its drift cannot be computed -- {found}'
    lost = unrenderable(found)
    if lost and not args.discard_drift:
        items = ''.join(f'\n  {item}' for item in lost)
        return (
            f'the account holds {len(lost)} item(s) the config source cannot render -- declare it in the config '
            f'source or accept its loss with {DISCARD}:{items}'
        )
    return lost


def ci_pause(
    argv: Sequence[str], *, home: Path, tools: Tools | None = None, redeem_with: cicron.Redeem | None = None
) -> int:
    """Refuse on drift, mark, then remove the marked lines; 0 paused (or already), 2 refused with nothing removed."""
    parser = _parser('ci-pause')
    parser.add_argument('--from', dest='clone', type=Path, required=True, help="the account's config-source clone")
    parser.add_argument('--host', required=True, help='the account file name, <cluster>-<user>')
    parser.add_argument(DISCARD, action='store_true', help='accept the loss of what the config source cannot render')
    args = parser.parse_args(list(argv))
    step, machine = Step(tools or Tools(), dry=args.dry_run), args.config or config_path()
    spec = _serving(machine)
    if isinstance(spec, str):
        emit(f'ci-pause refused: {spec}', err=True)
        return 2
    if marker(spec.root).is_file():
        emit(f'ci-pause: already CI-PAUSED ({marker(spec.root)}); {RESUME_DOOR} resumes it')
        return 0
    lost = _lost(step, home, machine, args)
    refused = lost if isinstance(lost, str) else not step.dry and _consented('ci-pause', step, args, redeem_with)
    if isinstance(lost, str) or refused:
        emit(f'ci-pause refused, nothing removed: {refused}', err=True)
        return 2
    marked = sum(MARK in line for line in step.read([*step.tools.crontab, '-l']).stdout.splitlines())
    discarded = f'{len(lost)} drift item(s) discarded'
    if step.dry:
        emit(f'[dry-run] would mark CI-PAUSED and remove {marked} marked line(s); {discarded}')
        return 0
    who = os.environ.get('USER') or os.environ.get('USERNAME', '?')
    marker(spec.root).parent.mkdir(parents=True, exist_ok=True)
    marker(spec.root).write_text(f'by {who} at {dt.datetime.now(dt.UTC):%Y-%m-%dT%H:%M:%SZ}; {discarded}\n', 'utf-8')
    if rc := crontab(step, []):
        return rc
    emit(f'ci-pause: removed {marked} marked crontab line(s); {discarded}')
    return 0


def ci_resume(
    argv: Sequence[str], *, home: Path, tools: Tools | None = None, redeem_with: cicron.Redeem | None = None
) -> int:
    """Rewrite the declared lines, verify them, delete the marker; 0 resumed, 2 refused or unverified."""
    args = _parser('ci-resume').parse_args(list(argv))
    step, machine = Step(tools or Tools(), dry=args.dry_run), args.config or config_path()
    spec = _serving(machine)
    slurm = deploy.slurm_dirs()  # the deploy's own resolution, so the lines are the deploy's
    if isinstance(spec, str) or isinstance(slurm, str):
        emit(f'ci-resume refused: {spec if isinstance(spec, str) else slurm}', err=True)
        return 2
    if not marker(spec.root).is_file():
        emit(f'ci-resume refused: no CI-PAUSED marker at {marker(spec.root)}; nothing to resume', err=True)
        return 2
    user = step.read([*step.tools.id, '-un']).stdout.strip()
    lines = cron_lines(spec, home, slurm=slurm, setup=grant_setup(machine, user))
    if not step.dry and (refused := _consented('ci-resume', step, args, redeem_with)):
        emit(f'ci-resume refused, nothing changed: {refused}', err=True)
        return 2
    if (rc := crontab(step, lines)) or step.dry:
        return rc
    held = step.read([*step.tools.crontab, '-l']).stdout.splitlines()
    if missing := [line for line in lines if line not in held]:
        emit(f'ci-resume: crontab -l lacks {len(missing)} declared line(s); the marker stays: {missing}', err=True)
        return 2
    marker(spec.root).unlink()
    emit(f'ci-resume: {len(lines)} marked crontab line(s) restored and verified; CI-PAUSED cleared')
    return 0


def main_pause(argv: Sequence[str]) -> int:
    """The on-account ``ci-pause`` verb."""
    return ci_pause(argv, home=Path.home())


def main_resume(argv: Sequence[str]) -> int:
    """The on-account ``ci-resume`` verb."""
    return ci_resume(argv, home=Path.home())
