"""A CODE IS NEVER ASKED ON A STALE PREFLIGHT: the green names its lifetime, and a no-code read names the re-run.

Incident 2026-11-22: ``sshhold open --plan --code C`` refused "no green preflight (the green one is 31161 s old)"
only AFTER the user had given the code, whose window then expired while the preflight re-ran. Nothing had said the
green lived an hour: the preflight's last line named no lifetime, and ``consent receipts`` -- the read a Stop hook
takes before an assistant may ask for a code -- did not know a plan's preflight at all.

PLANTED controls: the same reads on a fresh preflight exit 0 and say how long it still stands.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lab_commons.home import HOME_ENV
from test_dev_planrun import PLAN as STEPPED
from test_dev_planrun import STEPS, FakeHost, secret_here
from test_ops_consent_door import NOW, PLAN, Wire, issuer

from dev_lab.dev import planrunpreflight
from dev_lab.ops.consent import __main__ as consent_main
from dev_lab.ops.consent.credential import ConsentRefused
from dev_lab.ops.consent.door import PREFLIGHT_FRESH_S, offer, plan_preflights, record_preflight
from dev_lab.ops.consent.issuer import Issuer

__all__ = ['issuer', 'secret_here']

#: Past the backstop: the incident's 31161 s met a 3600 s lifetime; the lifetime is 24 h now, so this is a day more.
OLD = int(PREFLIGHT_FRESH_S) + 31161


def test_the_green_line_names_how_long_it_stands_and_the_no_code_check() -> None:
    green, lines = planrunpreflight.preflight(STEPPED, STEPS, lambda _dest: FakeHost())
    assert green, lines
    assert f'valid {PREFLIGHT_FRESH_S:.0f} s' in lines[-1]
    assert 'python -m dev_lab.ops.consent plan <plan.json>' in lines[-1]


def test_an_offer_answers_how_long_the_preflight_still_stands(issuer: Issuer, tmp_path: Path) -> None:
    record_preflight(PLAN, home=tmp_path, now=NOW)
    assert offer(PLAN, {}, send=Wire(issuer), home=tmp_path, now=NOW + 600) == PREFLIGHT_FRESH_S - 600
    with pytest.raises(ConsentRefused, match=rf'{OLD} s old; one is valid 86400 s\): re-run preflight'):
        offer(PLAN, {}, send=Wire(issuer), home=tmp_path, now=NOW + OLD)


def test_plan_preflights_lists_each_plan_with_the_seconds_it_has_left(tmp_path: Path) -> None:
    assert plan_preflights(home=tmp_path, now=NOW) == []
    record_preflight(PLAN, home=tmp_path, now=NOW)
    assert plan_preflights(home=tmp_path, now=NOW + 100) == [(PLAN.digest, PREFLIGHT_FRESH_S - 100)]
    assert plan_preflights(home=tmp_path, now=NOW + OLD) == [(PLAN.digest, PREFLIGHT_FRESH_S - OLD)]


def test_the_plan_verb_says_the_seconds_left_and_a_stale_one_names_the_rerun(
    issuer: Issuer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The no-code check to run right before asking: exit 0 with the seconds left, 2 naming ``re-run preflight``."""
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps({'hosts': list(PLAN.hosts), 'grants': list(PLAN.grants)}), encoding='utf-8')
    wire = Wire(issuer)
    record_preflight(PLAN)
    assert consent_main.main(['plan', str(path)], table={}, send=wire) == 0
    assert 's more' in capsys.readouterr().out
    monkeypatch.setattr('time.time', lambda: NOW + 10 * PREFLIGHT_FRESH_S)
    record_preflight(PLAN, now=NOW)
    asked = len(wire.sent)
    assert consent_main.main(['plan', str(path)], table={}, send=wire) == 2
    assert 're-run preflight' in capsys.readouterr().err
    assert len(wire.sent) == asked  # local: the stale read never reached the issuer, and no code exists to spend


def test_receipts_knows_a_plans_preflight_fresh_and_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The Stop hook's read: a fresh plan preflight admits the ask; a stale one is NAMED with its re-run door."""
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    monkeypatch.setattr('time.time', lambda: NOW + OLD)
    record_preflight(PLAN, now=NOW)
    assert consent_main.main(['receipts']) == 1
    said = capsys.readouterr().err
    assert f'plan {PLAN.digest[:12]}' in said
    assert f'{OLD} s old' in said
    assert 're-run preflight' in said
    record_preflight(PLAN, now=NOW + OLD - 60)  # PLANTED: the same plan, preflighted a minute ago
    assert consent_main.main(['receipts']) == 0
    assert f'plan {PLAN.digest[:12]} valid {PREFLIGHT_FRESH_S - 60:.0f} s more' in capsys.readouterr().out
