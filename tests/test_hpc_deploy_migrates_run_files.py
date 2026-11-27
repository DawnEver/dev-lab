"""The deploy migrates the account's forge run files once (FORMATS-MIGRATE-ONCE), so no tick meets a retired key.

Measured 2026-11-27: every serve tick of ezxmw9 and ezztz said ``carries retired key(s) 'artefact'``. The door
(:func:`dev_lab.dev.forgerunstate.migrate`) runs on the account itself, and an account is reached only through
the fleet: the deploy is its one door there, so the migration is a deploy phase.
"""

from __future__ import annotations

import pytest

from dev_lab.dev import forgerunstate
from dev_lab.dev.hpcaccount import deploy
from dev_lab.dev.hpcaccount.steps import Step, Tools


def _recorded(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    applied: list[bool] = []

    def migrate(*, apply: bool) -> tuple[str, ...]:
        applied.append(apply)
        return ('/h/forge-runs/x.json: renamed artefact -> artifact',)  # spelling-ignore-line

    monkeypatch.setattr(forgerunstate, 'migrate', migrate)
    return applied


def test_the_runs_phase_rewrites_on_a_deploy_and_only_lists_on_a_dry_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """PLANTED CONTROL: the dry run names the file yet never applies."""
    applied = _recorded(monkeypatch)
    assert deploy.runs(Step(Tools(), dry=True)) == 0
    assert deploy.runs(Step(Tools(), dry=False)) == 0
    assert applied == [False, True]
    assert capsys.readouterr().out.count('x.json: renamed') == 2


def test_every_role_migrates_before_its_cron_ticks() -> None:
    for serves in (False, True):
        phases = deploy.phases_of(serves=serves)
        assert 'runs' in phases
        if serves:
            assert phases.index('runs') < phases.index('cron')
