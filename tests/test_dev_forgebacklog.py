"""``dev_lab.dev.forgebacklog`` -- a ready PR waiting on ``tests/review`` past the bound pages once (2026-11-03).

The 11-02/03 backlog went unseen: lab-commons' review job could not import its method, posted no ``tests/review``,
and every PR there waited with nothing paging. PLANTED CONTROLS: a fresh head, a reviewed head and a draft raise
nothing; a head waiting past the bound with no status, or with a ``pending`` one, raises; it pages once.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from _forge_state import StateForge

from dev_lab.dev import forgebacklog
from dev_lab.dev.forgebacklog import DEFAULT_WAIT, alarms
from dev_lab.dev.forgeservesteps import raise_once

_NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)
_SHA = 'b' * 40


def _ready(monkeypatch: pytest.MonkeyPatch, age: timedelta, *, title: str = 'fix: x') -> tuple[StateForge, int]:
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', title=title, sha=_SHA)
    monkeypatch.setattr(forgebacklog, 'pushed', lambda _client, _sha: _NOW - age)
    return forge, number


def _post(forge: StateForge, state: str, description: str = '') -> None:
    forge.call(
        'POST', f'{forge.repo}/statuses/{_SHA}', {'context': 'tests/review', 'state': state, 'description': description}
    )


def test_a_fresh_head_a_reviewed_head_and_a_draft_raise_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    forge, _ = _ready(monkeypatch, DEFAULT_WAIT - timedelta(minutes=1))
    assert alarms(forge, 'integrate/main', 'o/r', now=_NOW) == []
    forge, _ = _ready(monkeypatch, DEFAULT_WAIT + timedelta(hours=1))
    _post(forge, 'success', 'review round 1: no blocking finding open')
    assert alarms(forge, 'integrate/main', 'o/r', now=_NOW) == []
    forge, _ = _ready(monkeypatch, DEFAULT_WAIT + timedelta(hours=1), title='WIP: fix: x')
    assert alarms(forge, 'integrate/main', 'o/r', now=_NOW) == []


@pytest.mark.parametrize(('state', 'shown'), [(None, 'no tests/review posted'), ('pending', 'pending: budget reached')])
def test_a_head_waiting_past_the_bound_raises_naming_the_pr_the_wait_and_the_remedy(
    monkeypatch: pytest.MonkeyPatch, state: str | None, shown: str
) -> None:
    forge, number = _ready(monkeypatch, timedelta(hours=9))
    if state:
        _post(forge, state, 'budget reached: 7.5/7.5 USD')
    (found,) = alarms(forge, 'integrate/main', 'o/r', now=_NOW)
    assert f'#{number}' in found.subject
    assert 'waited 9h' in found.body
    assert shown in found.body
    assert f'forge status list {_SHA}' in found.body
    paged: list[object] = []
    for _tick in range(2):
        raise_once(forge, 'integration', alarms(forge, 'integrate/main', 'o/r', now=_NOW), alarm=paged.append)
    assert len(paged) == 1


def test_the_bound_is_the_repos_declared_review_wait(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.review]\nbacklog = "2 h"\n', encoding='utf-8')
    assert forgebacklog.declared_wait(tmp_path) == timedelta(hours=2)
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    assert forgebacklog.declared_wait(tmp_path) == DEFAULT_WAIT
