"""A forge write refused for a private marker names its rule and its door, and the walls ledger records both.

Measured 2026-11-17: ``forge pr create`` refused a body naming a private value as ``[forge] PRIVATE-MARKERS: ...;
rewrite the text neutrally ... and re-run.`` and the ledger recorded rule ``unknown`` with ``remedy_present: false``:
the ``[forge]`` prefix hid the rule id from :func:`walls.rule_of` and the door shared the cause's line, so
:func:`walls.has_remedy` saw none. The fix is the shape forge sync took: ``PRIVATE-MARKERS: <cause>``, ``Door: ...``
on a line of its own, recorded through :func:`walls.refused_text`. Fixture markers are invented names only.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from _forge_fake import run_git

from dev_lab.dev import privatemarkers, walls
from dev_lab.dev.forgecli import issue_and_pr

_MARKERS = (re.compile('zorblaxhost', re.IGNORECASE),)


def test_the_refusal_leads_with_its_rule_and_puts_its_door_on_a_line_of_its_own() -> None:
    text = privatemarkers.text_refusal('ran on zorblaxhost', 'PR body', _MARKERS)
    assert text is not None
    lines = text.splitlines()
    assert lines[0].startswith('PRIVATE-MARKERS: '), text
    assert lines[1].startswith('Door: '), text
    assert 'zorblaxhost' not in text.lower()
    assert walls.rule_of(text) == 'PRIVATE-MARKERS'
    assert walls.has_remedy(text)
    assert not walls.has_remedy(' '.join(lines[:2])), 'PLANTED CONTROL: folded onto one line, no door'


def test_a_clean_body_is_not_refused() -> None:
    assert privatemarkers.text_refusal('ran on a build host', 'PR body', _MARKERS) is None


def test_the_create_door_records_the_wall_with_its_rule_and_a_door(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_git(tmp_path, 'init', '-q')
    denylist = tmp_path / 'private-markers'
    denylist.write_text('ZorblaxHost\n', encoding='utf-8')
    monkeypatch.setattr(privatemarkers, 'MARKERS_FILE', denylist)
    argv = ['pr', 'create', '--title', 't', '--body', 'ran on zorblaxhost', '--head', 'x', '--base', 'y']
    assert issue_and_pr(argv, cwd=tmp_path, env={}) == 1
    err = capsys.readouterr().err
    lines = err.splitlines()
    assert any(line.startswith('PRIVATE-MARKERS: ') for line in lines), err
    assert not any(line.startswith('[forge] PRIVATE-MARKERS') for line in lines), err
    rows = [json.loads(line) for line in walls.ledger(tmp_path).read_text(encoding='utf-8').splitlines()]
    assert [(row['rule'], row['remedy_present']) for row in rows] == [('PRIVATE-MARKERS', True)]
