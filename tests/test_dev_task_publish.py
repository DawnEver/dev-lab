"""v1 FAM-15: the task door publishes its own ledger write, and every verb names a clone ahead of its origin.

The origin is a LOCAL bare repository: no test reaches the network. The planted control is a clone one commit
ahead (the check fires) beside an in-sync clone (it stays silent).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from _task_ledger import plant_ledger

from dev_lab.dev import task, taskpublish
from dev_lab.dev._task_io import commit

_GIT = shutil.which('git') or 'git'


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        [_GIT, '-C', str(root), *args], check=True, capture_output=True, text=True, encoding='utf-8'
    ).stdout.strip()


@pytest.fixture
def clone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    for key, value in {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@x', 'GIT_COMMITTER_NAME': 't',
                       'GIT_COMMITTER_EMAIL': 't@x'}.items():  # fmt: skip
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(taskpublish, '_sleep', lambda _s: None)
    origin = tmp_path / 'origin.git'
    subprocess.run([_GIT, 'init', '-q', '--bare', str(origin)], check=True, capture_output=True)
    root = plant_ledger()
    _git(root, 'remote', 'add', 'origin', str(origin))
    (root / 'seed.md').write_text('seed\n', encoding='utf-8')
    _git(root, 'add', 'seed.md')
    _git(root, 'commit', '-q', '-m', 'seed')
    _git(root, 'push', '-q', 'origin', 'HEAD')
    return root


def _local_commit(root: Path, name: str) -> None:
    (root / name).write_text(name, encoding='utf-8')
    _git(root, 'add', name)
    _git(root, 'commit', '-q', '-m', name)


def test_an_in_sync_clone_stays_silent(clone: Path) -> None:
    assert taskpublish.ahead_warning(clone) is None


def test_a_clone_one_commit_ahead_is_named_with_its_door(clone: Path) -> None:
    _local_commit(clone, 'one.md')
    said = taskpublish.ahead_warning(clone)
    assert said is not None
    assert '1 commit ahead' in said
    assert taskpublish.door(clone) in said


def test_a_commit_through_the_door_reaches_the_origin(clone: Path) -> None:
    (clone / 'a.md').write_text('a', encoding='utf-8')
    commit(clone, 'chore(tasks): a', 'a.md')
    assert taskpublish.ahead_warning(clone) is None
    origin = Path(_git(clone, 'remote', 'get-url', 'origin'))
    assert _git(origin, 'log', '-1', '--format=%s') == 'chore(tasks): a'


def test_a_failed_publish_is_reported_by_name_and_never_fatal(clone: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _git(clone, 'remote', 'set-url', 'origin', str(clone.parent / 'gone.git'))
    (clone / 'b.md').write_text('b', encoding='utf-8')
    commit(clone, 'chore(tasks): b', 'b.md')
    assert _git(clone, 'log', '-1', '--format=%s') == 'chore(tasks): b', 'the local write stands'
    err = capsys.readouterr().err
    assert 'was not published' in err
    assert taskpublish.door(clone) in err


def test_every_verb_warns_while_the_clone_is_ahead(clone: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert task.main(['list'], cwd=clone) == 0
    assert 'ahead' not in capsys.readouterr().err
    _local_commit(clone, 'two.md')
    assert task.main(['list'], cwd=clone) == 0
    err = capsys.readouterr().err
    assert '1 commit ahead' in err
    assert taskpublish.door(clone) in err
