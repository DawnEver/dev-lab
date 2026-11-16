"""``ci-pause`` / ``ci-resume`` -- stop and restart a VERIFICATION account's forge CI cron around cluster maintenance.

Run ON the account; ``ci-pause-fleet`` / ``ci-resume-fleet`` start them
(:func:`dev_lab.dev.hpcaccount.backup.main_fleet`) on the selected accounts whose ``[deploy] role`` serves; a
research account has no CI cron by design and is skipped, or refused when named by ``--account``.

``ci-pause [--config <machine file>] [--dry-run]``: refuse a role that does not serve; back the account up first
(:func:`~dev_lab.dev.hpcaccount.backup.write_backup`) -- a backup that fails removes NOTHING; write the CI-PAUSED marker
(:mod:`~dev_lab.dev.hpcaccount.cimark`) naming the backup; then remove ONLY this tool's marked crontab lines
(:func:`~dev_lab.dev.hpcaccount.steps.crontab` with none), every other line kept. Running jobs are never touched:
this module runs no Slurm command at all.

``ci-resume [--config <machine file>] [--dry-run]``: refuse without the marker; rewrite the lines the deploy writes
from the account's declaration (:func:`~dev_lab.dev.hpcaccount.spec.cron_lines`, never a stale saved text), verify
``crontab -l`` holds each, and delete the marker.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
from collections.abc import Sequence
from pathlib import Path

from lab_commons.config import config_path
from lab_commons.log import emit

from dev_lab.dev.hpcaccount import deploy
from dev_lab.dev.hpcaccount.backup import write_backup
from dev_lab.dev.hpcaccount.cimark import RESUME_DOOR, marker
from dev_lab.dev.hpcaccount.spec import MARK, Deployment, cron_lines, grant_setup, load, ticked
from dev_lab.dev.hpcaccount.steps import Step, Tools, crontab

__all__ = ['ci_pause', 'ci_resume', 'main_pause', 'main_resume']


def _parsed(verb: str, argv: Sequence[str], tools: Tools | None) -> tuple[Step, Path]:
    parser = argparse.ArgumentParser(prog=f'dev_lab.dev.hpcaccount {verb}', description=__doc__.splitlines()[0])
    parser.add_argument('--config', type=Path, help='the rendered machine file (default: lab_commons.config)')
    parser.add_argument('--dry-run', action='store_true', help='print every action; change nothing')
    args = parser.parse_args(list(argv))
    return Step(tools or Tools(), dry=args.dry_run), args.config or config_path()


def _serving(machine: Path) -> Deployment | str:
    spec = load(machine) if machine.is_file() else None
    if spec is None:
        return f'no [deploy] in {machine}: deploy it with python -m dev_lab.dev.hpcaccount deploy-fleet'
    if not ticked(spec):
        return f'its [deploy] role {spec.role!r} does not serve: no CI cron by design, nothing to pause'
    return spec


def ci_pause(argv: Sequence[str], *, home: Path, tools: Tools | None = None) -> int:
    """Back up, mark, then remove the marked lines; 0 paused (or already), 2 refused with nothing removed."""
    step, machine = _parsed('ci-pause', argv, tools)
    spec = _serving(machine)
    if isinstance(spec, str):
        emit(f'ci-pause refused: {spec}', err=True)
        return 2
    if marker(home).is_file():
        emit(f'ci-pause: already CI-PAUSED ({marker(home)}); {RESUME_DOOR} resumes it')
        return 0
    written = write_backup(step, home, machine)
    if isinstance(written, str):
        emit(f'ci-pause refused, nothing removed: {written}', err=True)
        return 2
    marked = sum(MARK in line for line in step.read([*step.tools.crontab, '-l']).stdout.splitlines())
    if step.dry:
        emit(f'[dry-run] would back up into {written}, mark CI-PAUSED and remove {marked} marked line(s)')
        return 0
    who = os.environ.get('USER') or os.environ.get('USERNAME', '?')
    marker(home).write_text(f'backup {written} by {who} at {dt.datetime.now(dt.UTC):%Y-%m-%dT%H:%M:%SZ}\n', 'utf-8')
    if rc := crontab(step, []):
        return rc
    emit(f'ci-pause: backup {written}; removed {marked} marked crontab line(s)')
    return 0


def ci_resume(argv: Sequence[str], *, home: Path, tools: Tools | None = None) -> int:
    """Rewrite the declared lines, verify them, delete the marker; 0 resumed, 2 refused or unverified."""
    step, machine = _parsed('ci-resume', argv, tools)
    if not marker(home).is_file():
        emit(f'ci-resume refused: no CI-PAUSED marker at {marker(home)}; nothing to resume', err=True)
        return 2
    spec = _serving(machine)
    slurm = deploy._slurm_dirs()  # noqa: SLF001 -- the deploy's own resolution, so the lines are the deploy's
    if isinstance(spec, str) or isinstance(slurm, str):
        emit(f'ci-resume refused: {spec if isinstance(spec, str) else slurm}', err=True)
        return 2
    user = step.read([*step.tools.id, '-un']).stdout.strip()
    lines = cron_lines(spec, home, slurm=slurm, setup=grant_setup(machine, user))
    if (rc := crontab(step, lines)) or step.dry:
        return rc
    held = step.read([*step.tools.crontab, '-l']).stdout.splitlines()
    if missing := [line for line in lines if line not in held]:
        emit(f'ci-resume: crontab -l lacks {len(missing)} declared line(s); the marker stays: {missing}', err=True)
        return 2
    marker(home).unlink()
    emit(f'ci-resume: {len(lines)} marked crontab line(s) restored and verified; CI-PAUSED cleared')
    return 0


def main_pause(argv: Sequence[str]) -> int:
    """The on-account ``ci-pause`` verb."""
    return ci_pause(argv, home=Path.home())


def main_resume(argv: Sequence[str]) -> int:
    """The on-account ``ci-resume`` verb."""
    return ci_resume(argv, home=Path.home())
