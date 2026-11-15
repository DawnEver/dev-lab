"""``render`` removes what it rendered before and declares no longer -- and never a hand-written workflow.

dev-lab #424 stopped rendering ``review-again.yml`` for a judge repo; the stale file stayed, and ``check`` called it
hand-written on the repo's next relock.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import ciworkflows
from dev_lab.dev.ciworkflows import RENDERED_BY, STAMP, drift, main, write


@pytest.fixture
def github(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(ciworkflows, 'repo_forge', lambda _root: 'github')
    (tmp_path / 'pyproject.toml').write_text('', encoding='utf-8')
    return tmp_path


def test_the_stamp_starts_with_the_mark_a_render_is_known_by() -> None:
    assert STAMP.startswith(RENDERED_BY)


def test_a_file_rendered_before_and_declared_no_longer_is_removed(github: Path) -> None:
    """PLANTED CONTROL: a stale render, even under an older stamp, is gone after ``render`` and ``check`` is clean."""
    stale = github / '.github' / 'workflows' / 'gone.yml'
    stale.parent.mkdir(parents=True)
    stale.write_text(f'{RENDERED_BY}an older stamp\n{{}}\n', encoding='utf-8')
    assert [line for line in drift(github) if 'gone.yml' in line]
    assert main(['render', '--root', str(github)]) == 0
    assert not stale.exists()
    assert drift(github) == []


def test_a_hand_written_workflow_is_kept_and_still_refused(github: Path) -> None:
    """PLANTED CONTROL: a file without the stamp survives ``render`` and ``check`` still names it."""
    hand = github / '.github' / 'workflows' / 'hand.yml'
    hand.parent.mkdir(parents=True)
    hand.write_text('name: hand\n', encoding='utf-8')
    write(github)
    assert hand.read_text(encoding='utf-8') == 'name: hand\n'
    assert [line for line in drift(github) if 'hand.yml: a workflow no' in line]


def test_a_declared_workflow_is_rewritten_never_removed(github: Path) -> None:
    written = write(github)
    assert written
    assert write(github) == written
    assert all(path.is_file() for path in written)
