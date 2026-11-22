"""THE ISSUER SAYS WHICH DEV-LAB IT RUNS, with no code: its ``hello`` answer carries the installed commit.

Measured 2026-11-22: "is the host upgraded?" had no answer short of a code -- a host that already ran a fix but held
stale data read exactly like one that did not. The read-only handshake now carries the commit, and the two places an
agent reads it say it: the ``devhost bringup --check`` issuer wall and a plan's ``issuer: agrees`` line.

PLANTED CONTROL: an issuer that reports none (older than this report) is still green, and says it reports none.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_dev_bringup import _machine, _walls
from test_ops_consent_door import PLAN, Wire, issuer

from dev_lab.dev import planrunoffer
from dev_lab.ops.consent import door
from dev_lab.ops.consent.issuer import Issuer

__all__ = ['issuer']

SHA = 'ab12cd34ef56' + '0' * 28
GREEN = (True, ['step 1 ops.config: green', 'preflight: green, every door checked'])


def _answering(commit: str | None) -> door.Send:
    answer = {'fields': list(door.FIELDS), 'actions': sorted(door.ACTIONS)} | (
        {} if commit is None else {'dev_lab': commit}
    )
    return lambda _table, _request: (0, json.dumps(answer))


def test_hello_carries_the_installed_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(door, 'installed_commit', lambda: SHA)
    assert door.hello()['dev_lab'] == SHA
    assert door.handshake({}, send=_answering(SHA)) == SHA
    assert door.handshake({}, send=_answering(None)) == ''  # the control: an issuer that reports none still agrees


def test_the_installed_commit_is_read_from_the_distribution_and_empty_when_it_records_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Dist:
        def __init__(self, text: str | None) -> None:
            self.text = text

        def read_text(self, _name: str) -> str | None:
            return self.text

    recorded = json.dumps({'url': 'https://forge.example/x.git', 'vcs_info': {'vcs': 'git', 'commit_id': SHA}})
    for text, want in ((recorded, SHA), (None, ''), ('{"dir_info": {"editable": true}}', '')):
        monkeypatch.setattr(door.importlib.metadata, 'distribution', lambda _name, text=text: Dist(text))
        assert door.installed_commit() == want


def test_the_bringup_issuer_wall_says_the_commit_the_issuer_runs(tmp_path: Path) -> None:
    live = _machine(tmp_path)
    found = _walls(tmp_path, live, send=_answering(SHA))['issuer']
    assert found.green
    assert f'its dev-lab is {SHA[:12]}' in found.said
    silent = _walls(tmp_path, live, send=_answering(None))['issuer']  # the control
    assert silent.green
    assert 'reports no dev-lab commit' in silent.said


def test_a_plans_issuer_line_says_the_commit(issuer: Issuer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(door, 'installed_commit', lambda: SHA)
    green, lines = planrunoffer.offered(PLAN, GREEN, table={}, send=Wire(issuer), home=tmp_path)
    assert green
    assert f'issuer: agrees (runs dev-lab {SHA[:12]})' in lines[-1]
